"""Regiões de trade-location — modelo de domínio puro.

Espelha o `struct TradeLocation` do EA v4.60, mas separa:
  - `TradeLocation`: FATO imutável sobre o candle-sinal (nunca muda);
  - `RegionState`: ESTADO mutável do ciclo de vida (rompeu? consumiu?);
  - `RegionPhase`: enum explícito (evita combinações impossíveis de flags).

Zero dependências externas — só stdlib.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class RegionPhase(str, Enum):
    """Ciclo de vida de uma região (transições válidas em RegionManager)."""
    WAITING_BREAKOUT = "WAITING_BREAKOUT"   # criada, aguardando romper max/min
    BROKEN = "BROKEN"                       # rompeu, direção definida, SL/TP calculados
    CONSUMED = "CONSUMED"                   # TP/SL/fim do dia — não opera mais
    REARMED = "REARMED"                     # após SL com InpAllowReverse, espera novo rompimento


@dataclass(frozen=True, slots=True)
class TradeLocation:
    """Fato imutável sobre o candle-sinal. Nunca muda depois de criada.

    `bar_time` é a chave de identidade (único no timeframe).
    """
    bar_time: datetime
    high: float
    low: float
    volume: float
    big_candle: bool

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2.0

    @property
    def range_points(self) -> float:
        return self.high - self.low


@dataclass(slots=True)
class RegionState:
    """Estado mutável de uma região. Vive no RegionManager.

    `stop_loss` e `take_profit` só têm significado a partir de `phase == BROKEN`.
    `broken_time` só é preenchido em `BROKEN`.
    """
    location: TradeLocation
    phase: RegionPhase = RegionPhase.WAITING_BREAKOUT
    is_buy: bool = False
    stop_loss: float = 0.0
    take_profit: float = 0.0
    broken_time: datetime | None = None
    rearmed_once: bool = False  # para InpAllowReverse (limite de 1 rearme)

    @property
    def bar_time(self) -> datetime:
        return self.location.bar_time

    @property
    def volume(self) -> float:
        return self.location.volume

    @property
    def is_alive(self) -> bool:
        return self.phase in (RegionPhase.WAITING_BREAKOUT,
                              RegionPhase.BROKEN,
                              RegionPhase.REARMED)

    @property
    def can_be_candidate(self) -> bool:
        """Só regiões BROKEN são candidatas a entrada."""
        return self.phase == RegionPhase.BROKEN


class RegisterResult(str, Enum):
    """Motivo do `RegionManager.register()` — espelha os logs do EA."""
    CREATED = "CREATED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"       # já existe região nesse bar_time
    SKIPPED_FULL_QUEUE = "SKIPPED_FULL_QUEUE"     # MAX_LOC cheio e volume <= menor
    REPLACED_LOWEST = "REPLACED_LOWEST"           # MAX_LOC cheio, substituiu a de menor volume