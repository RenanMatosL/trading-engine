"""RealExecutor — ponte entre TradeIntent e BrokerGateway.

Calcula o volume final (sizing fixo em F3a), envia a ordem, devolve
ExecutionResult. Não gerencia posição — isso é F3b.
"""
from __future__ import annotations

from dataclasses import dataclass

import structlog

from engine.application.intent import TradeIntent
from engine.config.presets import StdDevV510Preset, SizingMode
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
        """Delega para OrderResult.is_ok."""
        return self.order_result.is_ok

    @property
    def ok(self) -> bool:
        """Alias retrocompatível (alguns testes chamam .ok)."""
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
        volume = self._compute_volume(info)
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

    def _compute_volume(self, info: SymbolInfo) -> float:
        risk = self._preset.risk
        if risk.sizing_mode == SizingMode.FIXED_CONTRACTS:
            raw = risk.total_contracts * risk.lot_per_contract
            return _normalize_lot(raw, info)
        return _normalize_lot(info.lots_min, info)