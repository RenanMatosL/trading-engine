"""RealExecutor — ponte entre TradeIntent e BrokerGateway (F3a + F5a).

Calcula o volume final (fixed_contracts ou by_risk), envia a ordem principal,
e arma as ordens limite das parciais (F5a).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog

from engine.application.intent import TradeIntent
from engine.config.presets import StdDevV510Preset, SizingMode, PartialExitType
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
                is_buy=not intent.is_buy,  # parcial fecha a posição → ordem contrária
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
    # Sizing — fixed_contracts (F3a) ou by_risk (F5b, ainda conservador)
    # ----------------------------------------------------------------
    def _compute_volume(self, info: SymbolInfo, intent: TradeIntent) -> float:
        risk = self._preset.risk
        if risk.sizing_mode == SizingMode.FIXED_CONTRACTS:
            raw = risk.total_contracts * risk.lot_per_contract
            return _normalize_lot(raw, info)
        # BY_RISK: fallback conservador (F5b implementa de verdade)
        return _normalize_lot(info.lots_min, info)