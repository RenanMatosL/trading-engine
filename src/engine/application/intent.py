"""Resultado de decisão do TradingSession.

- TradeIntent: "o Executor deve abrir/armar ordem com estes parâmetros"
- TickDecision: o que aconteceu no on_tick (intent + reentry_intent + diagnóstico)
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
class ReentryIntent:
    """Intenção de REFORÇO (F5c).

    Emitida pelo `TradingSession` quando o preço avança `reentry_arm_points`
    a favor e depois RETORNA ao preço de entrada. O `engine run` materializa
    via `executor.place_reentry_order(...)`.

    `entry_price`: preço de entrada original (o reforço entra neste preço).
    `contracts`: quantos contratos adicionar.
    `tp_points`: TP curto do reforço (a partir do `entry_price`).
    `sl_points`: SL do reforço (a partir do `entry_price`).
    """
    entry_price: float
    is_buy: bool
    contracts: int
    tp_points: float
    sl_points: float
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TickDecision:
    """Resultado do on_tick()."""
    intent: TradeIntent | None
    blocked_reason: str | None = None
    new_breakouts: int = 0
    expired: int = 0
    reentry_intent: ReentryIntent | None = None   # F5c


@dataclass(frozen=True, slots=True)
class BarResult:
    """Resultado do on_bar_closed()."""
    created: bool
    register_result: RegisterResult
    skipped_reason: str | None = None
    region: RegionState | None = None