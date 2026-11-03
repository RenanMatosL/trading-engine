"""Eventos de trade extraídos de `history_deals` (F3b + F5c).

O TradeEventPoller lê os deals do MT5 e classifica em 7 tipos:
  - EntryFilled:      a ordem de ENTRADA principal foi preenchida
  - PartialFilled:    uma parcial foi executada (comment "partial")
  - ReentryFilled:    a ordem de REFORÇO foi preenchida (F5c)
  - ReentryExitFilled: TP/SL do REFORÇO executou (F5c)
  - StopLossHit:      a posição bateu SL
  - TakeProfitHit:    a posição bateu TP
  - PositionClosed:   a posição fechou por motivo manual/fim do dia

O TradingSession consome esses eventos via `on_trade_event` e reage.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from engine.infrastructure.mt5.gateway import DealInfo


#+------------------------------------------------------------------+
#| Constantes (mapeamento dos DEAL_REASON do MT5)                   |
#+------------------------------------------------------------------+
DEAL_REASON_CLIENT = 0
DEAL_REASON_MOBILE = 1
DEAL_REASON_WEB = 2
DEAL_REASON_EXPERT = 3
DEAL_REASON_SL = 4
DEAL_REASON_TP = 5


#+------------------------------------------------------------------+
#| Eventos                                                          |
#+------------------------------------------------------------------+
@dataclass(frozen=True, slots=True)
class EntryFilled:
    """Ordem de entrada principal preenchida (posição aberta)."""
    deal: DealInfo
    position_ticket: int


@dataclass(frozen=True, slots=True)
class PartialFilled:
    """Parcial executada (fechamento parcial da posição)."""
    deal: DealInfo
    position_ticket: int
    remaining_volume: float


@dataclass(frozen=True, slots=True)
class ReentryFilled:
    """Ordem de REFORÇO preenchida (F5c).

    O reforço é uma entrada adicional na posição já aberta, no preço
    de entrada original, armada quando o preço avançou X pontos e voltou.
    """
    deal: DealInfo
    position_ticket: int


@dataclass(frozen=True, slots=True)
class ReentryExitFilled:
    """TP ou SL do REFORÇO executou (F5c)."""
    deal: DealInfo
    position_ticket: int
    is_tp: bool  # True = TP, False = SL


@dataclass(frozen=True, slots=True)
class StopLossHit:
    """Posição fechada por Stop Loss."""
    deal: DealInfo
    position_ticket: int


@dataclass(frozen=True, slots=True)
class TakeProfitHit:
    """Posição fechada por Take Profit."""
    deal: DealInfo
    position_ticket: int


@dataclass(frozen=True, slots=True)
class PositionClosed:
    """Posição fechada por motivo manual/fim do dia."""
    deal: DealInfo
    position_ticket: int


TradeEvent: TypeAlias = (
    EntryFilled
    | PartialFilled
    | ReentryFilled
    | ReentryExitFilled
    | StopLossHit
    | TakeProfitHit
    | PositionClosed
)