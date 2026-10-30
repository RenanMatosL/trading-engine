"""Porta de persistência de estado (F3c).

O domínio NUNCA importa SQLite, pydantic, structlog. Só conversa com o
Protocol `StateStore`. As implementações ficam em `infrastructure/state/`.

Snapshot serializável:
  - `SessionSnapshot`: estado completo da `TradingSession` (cooldown,
    contador diário, região do trade atual, posição atual).
  - `RegionState`: já é um dataclass serializável; `save_regions` /
    `load_regions` trafegam a lista inteira.

Datas sempre em ISO 8601 UTC (a serialização é responsabilidade da
implementação, não do domínio).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from engine.domain.strategy.location import RegionState


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Estado serializável da TradingSession.

    Todos os campos são opcionais para permitir "fresh start" (primeira
    execução) sem exigir dados.
    """
    last_sl_time: datetime | None = None
    trades_today: int = 0
    current_day: datetime | None = None
    current_entry_region: datetime | None = None
    current_entry_position: int | None = None


class StateStore(Protocol):
    """Porta de persistência. Implementações: InMemoryStateStore, SqliteStateStore."""

    def save_session(self, snapshot: SessionSnapshot) -> None: ...
    def load_session(self) -> SessionSnapshot | None: ...

    def save_regions(self, regions: list[RegionState]) -> None: ...
    def load_regions(self) -> list[RegionState]: ...

    def clear(self) -> None: ...