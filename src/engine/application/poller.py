"""TradeEventPoller — lê `history_deals` do MT5 e emite TradeEvents.

F3b: 5 tipos (EntryFilled, PartialFilled, StopLossHit, TakeProfitHit, PositionClosed)
F5c: +2 tipos (ReentryFilled, ReentryExitFilled) para o reforço.
"""
from __future__ import annotations

from datetime import datetime

import structlog

from engine.application.trade_events import (
    DEAL_REASON_SL,
    DEAL_REASON_TP,
    EntryFilled,
    PartialFilled,
    PositionClosed,
    ReentryExitFilled,
    ReentryFilled,
    StopLossHit,
    TakeProfitHit,
    TradeEvent,
)
from engine.infrastructure.mt5.gateway import BrokerGateway, DealInfo


log = structlog.get_logger()


def _classify_deal(deal: DealInfo) -> TradeEvent:
    """Classifica um DealInfo em um TradeEvent.

    Ordem de prioridade (do mais específico ao mais genérico):
      1. Entrada de REFORÇO (comment "reentry", is_entry=True)
      2. Saída de REFORÇO (comment "reentry_tp" ou "reentry_sl")
      3. Entrada principal (is_entry=True, resto)
      4. SL hit (reason=4)
      5. TP hit (reason=5)
      6. Parcial (comment "partial")
      7. Fechamento (resto)
    """
    comment_lower = (deal.comment or "").lower()

    # --- Reforço (F5c) ---
    if "reentry_tp" in comment_lower:
        return ReentryExitFilled(
            deal=deal, position_ticket=deal.position_ticket, is_tp=True,
        )
    if "reentry_sl" in comment_lower:
        return ReentryExitFilled(
            deal=deal, position_ticket=deal.position_ticket, is_tp=False,
        )
    if "reentry" in comment_lower and deal.is_entry:
        return ReentryFilled(deal=deal, position_ticket=deal.position_ticket)

    # --- Entrada principal ---
    if deal.is_entry:
        return EntryFilled(deal=deal, position_ticket=deal.position_ticket)

    # --- SL / TP ---
    if deal.reason == DEAL_REASON_SL:
        return StopLossHit(deal=deal, position_ticket=deal.position_ticket)
    if deal.reason == DEAL_REASON_TP:
        return TakeProfitHit(deal=deal, position_ticket=deal.position_ticket)

    # --- Parcial ---
    if "partial" in comment_lower:
        return PartialFilled(
            deal=deal,
            position_ticket=deal.position_ticket,
            remaining_volume=0.0,
        )

    # --- Fechamento ---
    return PositionClosed(deal=deal, position_ticket=deal.position_ticket)


class TradeEventPoller:
    """Lê `history_deals` e devolve só os eventos NOVOS desde o último poll."""

    def __init__(self) -> None:
        self._last_deal_ticket: int = 0

    def poll(
        self,
        gateway: BrokerGateway,
        *,
        since: datetime,
        symbol: str | None = None,
        magic: int | None = None,
    ) -> list[TradeEvent]:
        deals = gateway.history_deals(since, symbol=symbol, magic=magic)
        events: list[TradeEvent] = []
        max_ticket = self._last_deal_ticket

        for deal in deals:
            if deal.ticket <= self._last_deal_ticket:
                continue
            event = _classify_deal(deal)
            events.append(event)
            if deal.ticket > max_ticket:
                max_ticket = deal.ticket
            log.info(
                "trade_event",
                kind=type(event).__name__,
                ticket=deal.ticket,
                position=deal.position_ticket,
                volume=deal.volume,
                price=deal.price,
                reason=deal.reason,
                comment=deal.comment,
            )

        self._last_deal_ticket = max_ticket
        return events

    @property
    def last_deal_ticket(self) -> int:
        return self._last_deal_ticket

    def reset(self) -> None:
        self._last_deal_ticket = 0