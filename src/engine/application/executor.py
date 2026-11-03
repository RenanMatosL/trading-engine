"""RealExecutor — ponte entre TradeIntent e BrokerGateway (F3a + F5a + F5b).

Calcula o volume final (fixed_contracts ou by_risk), envia a ordem principal,
e arma as ordens limite das parciais (F5a).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog

from engine.application.intent import TradeIntent
from engine.config.presets import (
    PartialExitType,
    RiskMode,
    SizingMode,
    StdDevV510Preset,
)
from engine.infrastructure.mt5.gateway import (
    BrokerGateway,
    OrderRequest,
    OrderResult,
    SymbolInfo,
)


log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    intent: TradeIntent
    order_result: OrderResult
    volume: float
    symbol_info: SymbolInfo

    @property
    def is_ok(self) -> bool:
        return self.order_result.is_ok

    @property
    def ok(self) -> bool:
        return self.is_ok


def _normalize_lot(lot: float, info: SymbolInfo) -> float:
    step = info.lots_step if info.lots_step > 0 else 0.01
    lot = int(lot / step + 1e-7) * step
    if lot < info.lots_min:
        lot = info.lots_min
    if lot > info.lots_max:
        lot = info.lots_max
    return round(lot, 8)


class RealExecutor:
    """Executa TradeIntent no gateway (MT5 real ou FakeGateway)."""

    def __init__(self, gateway: BrokerGateway, preset: StdDevV510Preset) -> None:
        self._gw = gateway
        self._preset = preset

    # ----------------------------------------------------------------
    # Execução principal
    # ----------------------------------------------------------------
    def execute(self, intent: TradeIntent, *, symbol: str) -> ExecutionResult:
        info = self._gw.symbol_info(symbol)
        volume = self._compute_volume(info, intent)
        req = OrderRequest(
            symbol=symbol,
            is_buy=intent.is_buy,
            volume=volume,
            price=intent.entry_price,
            stop_loss=intent.stop_loss,
            take_profit=intent.take_profit,
            is_limit=intent.as_pending,
            comment=f"engine_{intent.reason}",
            magic=0,
        )
        result = self._gw.place_order(req)
        log.info(
            "executor_place_order",
            symbol=symbol,
            is_buy=intent.is_buy,
            volume=volume,
            price=intent.entry_price,
            is_limit=intent.as_pending,
            retcode=result.retcode,
            ok=result.is_ok,
        )
        return ExecutionResult(
            intent=intent,
            order_result=result,
            volume=volume,
            symbol_info=info,
        )

    # ----------------------------------------------------------------
    # Parciais (F5a)
    # ----------------------------------------------------------------
    def place_partial_orders(
        self, intent: TradeIntent, *, symbol: str
    ) -> list[OrderResult]:
        """Arma as ordens limite das parciais (F5a).

        Cada tier vira um `BuyLimit`/`SellLimit` no preço-alvo, com o
        volume do tier. O comment é `engine_partial_N` (N = tier_index+1),
        para o Poller classificar como `PartialFilled`.

        Retorna uma lista de `OrderResult` (um por tier armado).
        """
        if not intent.partials:
            return []

        risk = self._preset.risk
        if not risk.partial_as_pending:
            log.info(
                "partials_market_mode",
                detail="partial_as_pending=False — parciais executadas a mercado pelo Executor",
            )
            return []

        info = self._gw.symbol_info(symbol)
        results: list[OrderResult] = []

        for spec in intent.partials:
            target_price = spec.target_price(
                intent.entry_price, intent.is_buy, risk.exit_type,
            )
            volume = _normalize_lot(float(spec.contracts), info)
            if volume < info.lots_min:
                log.warning(
                    "partial_volume_below_min",
                    tier=spec.tier_index,
                    volume=volume,
                    lots_min=info.lots_min,
                )
                continue

            req = OrderRequest(
                symbol=symbol,
                is_buy=not intent.is_buy,
                volume=volume,
                price=target_price,
                stop_loss=0.0,
                take_profit=0.0,
                is_limit=True,
                comment=f"engine_partial_{spec.tier_index + 1}",
                magic=0,
            )
            res = self._gw.place_order(req)
            log.info(
                "executor_place_partial",
                tier=spec.tier_index,
                is_buy=intent.is_buy,
                volume=volume,
                price=target_price,
                retcode=res.retcode,
                ok=res.is_ok,
            )
            results.append(res)

        return results

        # ----------------------------------------------------------------
    # Reforço no retorno à entrada (F5c)
    # ----------------------------------------------------------------
    def place_reentry_order(
        self,
        *,
        symbol: str,
        price: float,
        is_buy: bool,
        contracts: int,
    ) -> OrderResult:
        """Arma a ordem limite do REFORÇO (F5c).

        A ordem é no mesmo sentido da posição (compra → BuyLimit no preço
        de entrada; venda → SellLimit). `comment=engine_reentry` para o
        Poller classificar como `ReentryFilled`.

        A ordem **não** tem SL/TP (eles são armados separados no fill).
        """
        info = self._gw.symbol_info(symbol)
        volume = _normalize_lot(float(contracts), info)
        if volume < info.lots_min:
            log.warning(
                "reentry_volume_below_min",
                contracts=contracts, volume=volume, lots_min=info.lots_min,
            )
            return OrderResult(
                retcode=-1, order_ticket=0, deal_ticket=0,
                message=f"reentry volume {volume} < lots_min {info.lots_min}",
            )

        req = OrderRequest(
            symbol=symbol,
            is_buy=is_buy,
            volume=volume,
            price=price,
            stop_loss=0.0,
            take_profit=0.0,
            is_limit=True,
            comment="engine_reentry",
            magic=0,
        )
        res = self._gw.place_order(req)
        log.info(
            "executor_place_reentry",
            symbol=symbol, is_buy=is_buy, volume=volume,
            price=price, retcode=res.retcode, ok=res.is_ok,
        )
        return res

    def place_reentry_exits(
        self,
        *,
        symbol: str,
        entry_price: float,
        is_buy: bool,
        contracts: int,
        tp_points: float,
        sl_points: float,
    ) -> list[OrderResult]:
        """Arma TP e SL do REFORÇO (F5c).

        Duas ordens separadas:
          - TP: limite no sentido contrário (`entry ± tp_points`)
          - SL: stop no sentido contrário (`entry ∓ sl_points`)

        `comment=engine_reentry_tp` / `engine_reentry_sl` para o Poller
        classificar como `ReentryExitFilled`.
        """
        info = self._gw.symbol_info(symbol)
        volume = _normalize_lot(float(contracts), info)
        if volume < info.lots_min:
            log.warning(
                "reentry_exits_volume_below_min",
                contracts=contracts, volume=volume, lots_min=info.lots_min,
            )
            return []

        if is_buy:
            tp_price = entry_price + tp_points
            sl_price = entry_price - sl_points
        else:
            tp_price = entry_price - tp_points
            sl_price = entry_price + sl_points

        # TP: ordem limite no sentido contrário (fecha o reforço)
        tp_req = OrderRequest(
            symbol=symbol,
            is_buy=not is_buy,
            volume=volume,
            price=tp_price,
            stop_loss=0.0,
            take_profit=0.0,
            is_limit=True,
            comment="engine_reentry_tp",
            magic=0,
        )
        tp_res = self._gw.place_order(tp_req)

        # SL: ordem stop no sentido contrário
        # SL: ordem stop no sentido contrário
        # SL: ordem stop no sentido contrário (F5e: is_stop=True)
        sl_req = OrderRequest(
            symbol=symbol,
            is_buy=not is_buy,
            volume=volume,
            price=sl_price,
            stop_loss=0.0,
            take_profit=0.0,
            is_limit=False,
            is_stop=True,                # F5e: stop explícito
            comment="engine_reentry_sl",
            magic=0,
        )
        sl_res = self._gw.place_order(sl_req)

        log.info(
            "executor_place_reentry_exits",
            symbol=symbol, is_buy=is_buy, volume=volume,
            tp_price=tp_price, sl_price=sl_price,
            tp_ok=tp_res.is_ok, sl_ok=sl_res.is_ok,
        )
        return [tp_res, sl_res]

    # ----------------------------------------------------------------
    # Gestão de posições
    # ----------------------------------------------------------------
    def cancel(self, ticket: int) -> OrderResult:
        return self._gw.cancel_order(ticket)

    def close(self, ticket: int) -> OrderResult:
        return self._gw.close_position(ticket)

    def modify(
        self, ticket: int, *, stop_loss: float, take_profit: float
    ) -> OrderResult:
        return self._gw.modify_position(
            ticket, stop_loss=stop_loss, take_profit=take_profit,
        )

    def close_all_at_end_of_day(
        self, symbol: str, now: datetime
    ) -> list[OrderResult]:
        """Fecha todas as posições abertas no símbolo (day trade, fim do dia)."""
        results: list[OrderResult] = []

        for order in self._gw.orders(symbol):
            res = self._gw.cancel_order(order.ticket)
            log.info(
                "end_of_day_cancel_order",
                ticket=order.ticket, ok=res.is_ok, retcode=res.retcode,
            )
            results.append(res)

        for pos in self._gw.positions(symbol):
            res = self._gw.close_position(pos.ticket)
            log.info(
                "end_of_day_close_position",
                ticket=pos.ticket, ok=res.is_ok, retcode=res.retcode,
            )
            results.append(res)

        return results

    # ----------------------------------------------------------------
    # Sizing — fixed_contracts (F3a) ou by_risk (F5b)
    # ----------------------------------------------------------------
    def _compute_volume(self, info: SymbolInfo, intent: TradeIntent) -> float:
        """Calcula o volume final.

        - FIXED_CONTRACTS: `total_contracts * lot_per_contract` (normalizado).
        - BY_RISK: calcula o lote pelo risco (fixed_money ou % do balance),
          usando `abs(entry - stop_loss)` e `tick_size`/`tick_value` do símbolo.

        Em BY_RISK, `total_contracts` é IGNORADO (espelha o EA).
        Se `risk_value=0` ou `sl_dist=0`, retorna `lots_min` (fallback).
        """
        risk = self._preset.risk

        # --- Fixed contracts (F3a) ---
        if risk.sizing_mode == SizingMode.FIXED_CONTRACTS:
            raw = risk.total_contracts * risk.lot_per_contract
            return _normalize_lot(raw, info)

        # --- By-risk (F5b) ---
        sl_dist = abs(intent.entry_price - intent.stop_loss)
        if sl_dist <= 0.0:
            log.warning(
                "by_risk_sl_dist_zero",
                entry=intent.entry_price, stop=intent.stop_loss,
                fallback="lots_min",
            )
            return _normalize_lot(info.lots_min, info)

        if info.tick_size <= 0.0 or info.tick_value <= 0.0:
            log.warning(
                "by_risk_symbol_info_invalido",
                tick_size=info.tick_size, tick_value=info.tick_value,
                fallback="lots_min",
            )
            return _normalize_lot(info.lots_min, info)

        loss_per_lot = (sl_dist / info.tick_size) * info.tick_value
        if loss_per_lot <= 0.0:
            return _normalize_lot(info.lots_min, info)

        risk_money = self._compute_risk_money(risk, self._gw)
        if risk_money <= 0.0:
            return _normalize_lot(info.lots_min, info)

        raw_lot = risk_money / loss_per_lot
        return _normalize_lot(raw_lot, info)

    @staticmethod
    def _compute_risk_money(risk, gateway) -> float:
        """Retorna o dinheiro em risco conforme o `risk_mode`.

        - FIXED_MONEY: `risk_value` (ex: 500 = R$ 500)
        - PERCENT_BALANCE: `balance * risk_value / 100` (ex: 1.0 = 1%)
        """
        if risk.risk_mode == RiskMode.FIXED_MONEY:
            return float(risk.risk_value)

        if risk.risk_mode == RiskMode.PERCENT_BALANCE:
            try:
                account = gateway.account()
                balance = float(account.balance)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "by_risk_account_falhou", erro=str(exc),
                    fallback="lots_min",
                )
                return 0.0
            return balance * float(risk.risk_value) / 100.0

        return 0.0