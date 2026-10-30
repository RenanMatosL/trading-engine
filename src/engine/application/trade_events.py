"""Eventos de trade extraídos de `history_deals` (F3b).

O TradeEventPoller lê os deals do MT5 e classifica em 5 tipos:
  - EntryFilled:    a ordem de ENTRADA foi preenchida
  - PartialFilled:  uma parcial foi executada (comment contém "partial")
  - StopLossHit:    a posição bateu SL
  - TakeProfitHit:  a posição bateu TP
  - PositionClosed: a posição fechou por motivo manual/fim do dia

O TradingSession consome esses eventos via `on_trade_event` e reage
(cooldown, rearme de região, consumo, contador diário).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from engine.infrastructure.mt5.gateway import DealInfo


#+------------------------------------------------------------------+
#| Constantes (mapeamento dos DEAL_REASON do MT5)                   |
#+------------------------------------------------------------------+
DEAL_REASON_CLIENT = 0   # fechamento manual / ordem do cliente
DEAL_REASON_MOBILE = 1
DEAL_REASON_WEB = 2
DEAL_REASON_EXPERT = 3   # fechamento por EA
DEAL_REASON_SL = 4       # stop loss
DEAL_REASON_TP = 5       # take profit


#+------------------------------------------------------------------+
#| Eventos                                                          |
#+------------------------------------------------------------------+
@dataclass(frozen=True, slots=True)
class EntryFilled:
    """Ordem de entrada preenchida (posição aberta)."""
    deal: DealInfo
    position_ticket: int


@dataclass(frozen=True, slots=True)
class PartialFilled:
    """Parcial executada (fechamento parcial da posição)."""
    deal: DealInfo
    position_ticket: int
    remaining_volume: float  # preenchido pelo TradingSession


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
    EntryFilled | PartialFilled | StopLossHit | TakeProfitHit | PositionClosed
)