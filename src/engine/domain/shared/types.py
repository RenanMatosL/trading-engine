"""Tipos fundamentais do dominio - puros, sem dependencia externa."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class VolumeSource(str, Enum):
    TICK = "tick"
    REAL = "real"


@dataclass(frozen=True, slots=True)
class Bar:
    """Candle FECHADO do timeframe de analise."""
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: float
    real_volume: float

    def volume(self, source: VolumeSource) -> float:
        if source is VolumeSource.REAL and self.real_volume > 0:
            return self.real_volume
        return self.tick_volume

    @property
    def range_points(self) -> float:
        return self.high - self.low

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2.0



@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Fotografia do mercado no instante do tick.

    `now` é sempre hora do SERVIDOR da corretora (mesma convenção do EA).
    `spread` fica disponível para uso futuro (F3+); hoje não é usado.
    """
    ask: float
    bid: float
    now: datetime
    spread: float = 0.0

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2.0