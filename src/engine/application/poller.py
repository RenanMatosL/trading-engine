"""TradeEventPoller — lê `history_deals` do MT5 e emite TradeEvents.

Estado: `_last_deal_ticket` (idempotência). A cada `poll()`:
  - Lê deals desde `since` (janela ampla) filtrados por symbol/magic;
  - Filtra `ticket > _last_deal_ticket` (só novos);
  - Classifica cada deal em um TradeEvent (via `_classify_deal`);
  - Atualiza `_last_deal_ticket` para o maior ticket visto.

O caller (`engine run` em F3d) chama `poll()` a cada N ticks e passa os
eventos para `TradingSession.on_trade_event(event, now)`.
"""
from __future__ import annotations

from datetime import datetime

import structlog

from engine.application.trade_events import (
    DEAL_REASON_CLIENT,
    DEAL_REASON_SL,
    DEAL_REASON_TP,
    EntryFilled,
    PartialFilled,
    PositionClosed,
    StopLossHit,
    TakeProfitHit,
    TradeEvent,
)
from engine.infrastructure.mt5.gateway import BrokerGateway, DealInfo


log = structlog.get_logger()


def _classify_deal(deal: DealInfo) -> TradeEvent:
    """Classifica um DealInfo em um TradeEvent.

    Regras:
      - is_entry=True                            → EntryFilled
      - is_entry=False + reason=SL (4)           → StopLossHit
      - is_entry=False + reason=TP (5)           → TakeProfitHit
      - is_entry=False + comment contém "partial"→ PartialFilled
      - is_entry=False + resto                   → PositionClosed
    """
    if deal.is_entry:
        return EntryFilled(deal=deal, position_ticket=deal.position_ticket)

    if deal.reason == DEAL_REASON_SL:
        return StopLossHit(deal=deal, position_ticket=deal.position_ticket)

    if deal.reason == DEAL_REASON_TP:
        return TakeProfitHit(deal=deal, position_ticket=deal.position_ticket)

    if "partial" in deal.comment.lower():
        return PartialFilled(
            deal=deal,
            position_ticket=deal.position_ticket,
            remaining_volume=0.0,  # TradingSession enriquece
        )

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
        """Retorna os eventos novos (posteriores a `_last_deal_ticket`)."""
        deals = gateway.history_deals(since, symbol=symbol, magic=magic)
        events: list[TradeEvent] = []
        max_ticket = self._last_deal_ticket

        for deal in deals:
            if deal.ticket <= self._last_deal_ticket:
                continue  # já processado em poll anterior
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
            )

        self._last_deal_ticket = max_ticket
        return events

    # ----------------------------------------------------------------
    # Inspeção (testes)
    # ----------------------------------------------------------------
    @property
    def last_deal_ticket(self) -> int:
        return self._last_deal_ticket

    def reset(self) -> None:
        self._last_deal_ticket = 0