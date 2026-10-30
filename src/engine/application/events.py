"""Tipos de evento do EventFeed — Bar + Tick em ordem cronológica.

O `Event` é a unidade de tempo do simulador: ou é uma Bar fechada
(dispara on_bar_closed no TradingSession) ou é um Tick (dispara on_tick).

O EventFeed é construído pelo caller com a fita que quiser simular —
permite testar cenários exóticos (ex.: dois ticks antes do candle fechar).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, TypeAlias

from engine.domain.shared.types import Bar, MarketSnapshot


@dataclass(frozen=True, slots=True)
class BarEvent:
    """Candle fechado + z-score pré-calculado (evita recalcular no loop)."""
    bar: Bar
    zscore: float

    @property
    def time(self) -> datetime:
        return self.bar.time


@dataclass(frozen=True, slots=True)
class TickEvent:
    """Snapshot de mercado (ask/bid/now)."""
    snapshot: MarketSnapshot

    @property
    def time(self) -> datetime:
        return self.snapshot.now


Event: TypeAlias = BarEvent | TickEvent


class EventFeed:
    """Itera uma fita de eventos em ordem cronológica.

    Responsabilidades:
      - garantir que o próximo evento é o de menor timestamp;
      - rejeitar eventos fora de ordem (sanity);
      - permitir inspeção do último processado.
    """

    def __init__(self, events: list[Event]) -> None:
        for i in range(1, len(events)):
            if events[i].time < events[i - 1].time:
                raise ValueError(
                    f"EventFeed fora de ordem: "
                    f"index {i} ({events[i].time}) < index {i-1} ({events[i-1].time})"
                )
        self._events = list(events)
        self._idx = 0

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def __next__(self) -> Event:
        if self._idx >= len(self._events):
            raise StopIteration
        event = self._events[self._idx]
        self._idx += 1
        return event

    def __getitem__(self, idx: int) -> Event:
        return self._events[idx]