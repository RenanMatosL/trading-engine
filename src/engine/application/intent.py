"""Resultado de decisão do TradingSession.

- TradeIntent: "o Executor deve abrir/armar ordem com estes parâmetros"
- TickDecision: o que aconteceu no on_tick (intent + diagnóstico)
- BarResult:    o que aconteceu no on_bar_closed (região criada ou motivo de skip)

Todos imutáveis. Zero dependência de MT5 ou de ordens.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from engine.application.partial_spec import PartialSpec
from engine.domain.strategy.location import RegionState, RegisterResult


@dataclass(frozen=True, slots=True)
class TradeIntent:
    """Intenção de trade pronta para o Executor executar.

    `volume` fica 0.0 até o Executor calcular (que tem SymbolInfo do MT5).
    `as_pending=True` → Executor usa BuyLimit/SellLimit.
    `as_pending=False` → Executor usa Buy/Sell (a mercado).

    `partials` (F5a): tupla de `PartialSpec` (ou None se o preset tem
    `use_partial_exit=False`). O Executor arma ordens limite para cada tier.
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
    partials: tuple[PartialSpec, ...] | None = None

    @property
    def bar_time(self) -> datetime:
        return self.region.bar_time


@dataclass(frozen=True, slots=True)
class TickDecision:
    """Resultado do on_tick()."""
    intent: TradeIntent | None
    blocked_reason: str | None = None
    new_breakouts: int = 0
    expired: int = 0


@dataclass(frozen=True, slots=True)
class BarResult:
    """Resultado do on_bar_closed()."""
    created: bool
    register_result: RegisterResult
    skipped_reason: str | None = None
    region: RegionState | None = None