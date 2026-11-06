"""Porta de persistência de estado (F3c + F5e + F7b-1).

O domínio NUNCA importa SQLite, pydantic, structlog. Só conversa com o
Protocol `StateStore`. As implementações ficam em `infrastructure/state/`.

Snapshot serializável:
  - `SessionSnapshot`: estado da sessão (cooldown, contador diário, parciais, reforço).
  - `RegionState`: já é um dataclass serializável.
  - `TradeRecord` (F7b-1): trade fechado (para o dashboard).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from engine.domain.strategy.location import RegionState


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Estado serializável da TradingSession."""
    last_sl_time: datetime | None = None
    trades_today: int = 0
    current_day: datetime | None = None
    current_entry_region: datetime | None = None
    current_entry_position: int | None = None
    # F5e: persistência de parciais/reforço
    current_entry_price: float | None = None
    current_is_buy: bool | None = None
    reentry_armed: bool = False
    reentry_done: bool = False
    partials_filled: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """Trade FECHADO (F7b-1).

    Gravado quando o trade é fechado (SL/TP/close/fim do dia).
    Usado pelo dashboard (`/api/trades`) e pela equity curve (`/api/equity`).
    """
    id: int | None                # None = ainda não persistido
    region_bar_time: datetime
    is_buy: bool
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    stop_loss: float
    take_profit: float
    initial_volume: float
    pnl_points: float
    pnl_money: float
    exit_reason: str              # "stop_loss" / "take_profit" / "end_of_day" / "partial"


class StateStore(Protocol):
    """Porta de persistência. Implementações: InMemoryStateStore, SqliteStateStore."""

    def save_session(self, snapshot: SessionSnapshot) -> None: ...
    def load_session(self) -> SessionSnapshot | None: ...

    def save_regions(self, regions: list[RegionState]) -> None: ...
    def load_regions(self) -> list[RegionState]: ...

    # F7b-1: trades
    def save_trade(self, trade: TradeRecord) -> int: ...
    def list_trades(self, limit: int = 50) -> list[TradeRecord]: ...
    def list_equity(self, limit: int = 1000) -> list[tuple[datetime, float]]: ...

    def clear(self) -> None: ...