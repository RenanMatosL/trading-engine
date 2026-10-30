"""Resultado de decisão do TradingSession.

- TradeIntent: "o Executor deve abrir/armar ordem com estes parâmetros"
- TickDecision: o que aconteceu no on_tick (intent + diagnóstico)
- BarResult:    o que aconteceu no on_bar_closed (região criada ou motivo de skip)

Todos imutáveis. Zero dependência de MT5 ou de ordens.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from engine.domain.strategy.location import RegionState, RegisterResult


@dataclass(frozen=True, slots=True)
class TradeIntent:
    """Intenção de trade pronta para o Executor executar.

    `volume` fica 0.0 até o Executor calcular (que tem SymbolInfo do MT5).
    `as_pending=True` → Executor usa BuyLimit/SellLimit.
    `as_pending=False` → Executor usa Buy/Sell (a mercado).
    """
    region: RegionState
    is_buy: bool
    entry_price: float
    stop_loss: float
    take_profit: float
    volume: float
    as_pending: bool
    reason: str
    created_at: datetime

    @property
    def bar_time(self) -> datetime:
        return self.region.bar_time


@dataclass(frozen=True, slots=True)
class TickDecision:
    """Resultado do on_tick()."""
    intent: TradeIntent | None
    blocked_reason: str | None = None   # None = livre; str = filtro ativo
    new_breakouts: int = 0               # quantas regiões romperam neste tick
    expired: int = 0                     # quantas expiraram neste tick


@dataclass(frozen=True, slots=True)
class BarResult:
    """Resultado do on_bar_closed()."""
    created: bool
    register_result: RegisterResult
    skipped_reason: str | None = None   # mute_open_min, duplicate, full_queue...
    region: RegionState | None = None