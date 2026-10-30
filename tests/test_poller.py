"""Golden tests do TradeEventPoller (F3b).

Cobre:
  - classificação de deals em 5 tipos de evento;
  - idempotência (dois poll() seguidos sem deals novos → vazio);
  - filtros por symbol e magic;
  - integração com FakeGateway + RealExecutor.

Não testa: reações do TradingSession (esses ficam em test_trading_session.py,
quando o patch de F3b for aplicado).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from engine.application.poller import (
    DEAL_REASON_CLIENT,
    DEAL_REASON_SL,
    DEAL_REASON_TP,
    TradeEventPoller,
)
from engine.application.trade_events import (
    EntryFilled,
    PartialFilled,
    PositionClosed,
    StopLossHit,
    TakeProfitHit,
)
from engine.infrastructure.mt5.fake import FakeGateway
from engine.infrastructure.mt5.gateway import DealInfo

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
TICK = timedelta(minutes=1)


#+------------------------------------------------------------------+
#| Helpers para construir deals sintéticos                          |
#+------------------------------------------------------------------+
def _deal(
    *,
    ticket: int,
    order_ticket: int | None = None,
    position_ticket: int = 5000,
    symbol: str = "WIN$N",
    is_buy: bool = True,
    volume: float = 6.0,
    price: float = 1100.0,
    is_entry: bool = False,
    magic: int = 0,
    comment: str = "",
    time_offset_min: int = 0,
    reason: int = DEAL_REASON_CLIENT,
) -> DealInfo:
    return DealInfo(
        ticket=ticket,
        order_ticket=order_ticket if order_ticket is not None else ticket,
        position_ticket=position_ticket,
        symbol=symbol,
        is_buy=is_buy,
        volume=volume,
        price=price,
        is_entry=is_entry,
        magic=magic,
        comment=comment,
        time=T0 + timedelta(minutes=time_offset_min),
        reason=reason,
    )


class _FakeGatewayWithDeals:
    """Gateway mínimo que só responde `history_deals`.

    Não precisa implementar o Protocol inteiro — só o método que o poller usa.
    """

    def __init__(self, deals: list[DealInfo]) -> None:
        self._deals = list(deals)

    def history_deals(
        self,
        since: datetime,
        *,
        symbol: str | None = None,
        magic: int | None = None,
    ) -> list[DealInfo]:
        out = []
        for d in self._deals:
            if d.time < since:
                continue
            if symbol and d.symbol != symbol:
                continue
            if magic is not None and d.magic != magic:
                continue
            out.append(d)
        return out

    def add_deal(self, d: DealInfo) -> None:
        """Para testes de idempotência (adicionar depois)."""
        self._deals.append(d)


#+------------------------------------------------------------------+
#| 1. EntryFilled — deal de ENTRADA                                |
#+------------------------------------------------------------------+
def test_poller_entry_filled():
    gw = _FakeGatewayWithDeals([
        _deal(ticket=100, is_entry=True, reason=DEAL_REASON_CLIENT, time_offset_min=10),
    ])
    poller = TradeEventPoller()

    events = poller.poll(gw, since=T0, symbol="WIN$N", magic=0)

    assert len(events) == 1
    assert isinstance(events[0], EntryFilled)
    assert events[0].deal.ticket == 100
    assert events[0].position_ticket == 5000


#+------------------------------------------------------------------+
#| 2. StopLossHit — reason SL (4)                                  |
#+------------------------------------------------------------------+
def test_poller_stop_loss_hit():
    gw = _FakeGatewayWithDeals([
        _deal(ticket=101, is_entry=False, reason=DEAL_REASON_SL, time_offset_min=15),
    ])
    poller = TradeEventPoller()

    events = poller.poll(gw, since=T0, symbol="WIN$N", magic=0)

    assert len(events) == 1
    assert isinstance(events[0], StopLossHit)
    assert events[0].deal.ticket == 101


#+------------------------------------------------------------------+
#| 3. TakeProfitHit — reason TP (5)                                |
#+------------------------------------------------------------------+
def test_poller_take_profit_hit():
    gw = _FakeGatewayWithDeals([
        _deal(ticket=102, is_entry=False, reason=DEAL_REASON_TP, time_offset_min=20),
    ])
    poller = TradeEventPoller()

    events = poller.poll(gw, since=T0, symbol="WIN$N", magic=0)

    assert len(events) == 1
    assert isinstance(events[0], TakeProfitHit)
    assert events[0].deal.ticket == 102


#+------------------------------------------------------------------+
#| 4. PositionClosed — fechamento manual (reason CLIENT + volume)  |
#+------------------------------------------------------------------+
def test_poller_position_closed():
    """Deal de saída sem SL/TP e com volume total da posição → PositionClosed."""
    gw = _FakeGatewayWithDeals([
        _deal(ticket=103, is_entry=False, reason=DEAL_REASON_CLIENT,
              volume=6.0, time_offset_min=25),
    ])
    poller = TradeEventPoller()

    events = poller.poll(gw, since=T0, symbol="WIN$N", magic=0)

    assert len(events) == 1
    assert isinstance(events[0], PositionClosed)
    assert events[0].deal.ticket == 103


#+------------------------------------------------------------------+
#| 5. PartialFilled — fechamento manual com volume parcial         |
#+------------------------------------------------------------------+
def test_poller_partial_filled():
    """Deal de saída manual com volume < total da posição → PartialFilled.

    O poller não sabe o volume inicial da posição sozinho; a heurística
    usada é: se o deal de saída tem volume > 0 e o comment não é "close"
    completo, classifica como PartialFilled. A distinção exata
    (PartialFilled vs PositionClosed manual) fica no TradingSession.
    """
    gw = _FakeGatewayWithDeals([
        _deal(ticket=104, is_entry=False, reason=DEAL_REASON_CLIENT,
              volume=3.0, comment="partial", time_offset_min=22),
    ])
    poller = TradeEventPoller()

    events = poller.poll(gw, since=T0, symbol="WIN$N", magic=0)

    assert len(events) == 1
    assert isinstance(events[0], PartialFilled)
    assert events[0].deal.ticket == 104
    # O poller devolve remaining_volume como 0.0 (não tem como saber).
    # O TradingSession enriquece com o volume atual da posição.


#+------------------------------------------------------------------+
#| 6. Idempotência — 2 polls seguidos sem deal novo → vazio        |
#+------------------------------------------------------------------+
def test_poller_idempotente():
    gw = _FakeGatewayWithDeals([
        _deal(ticket=105, is_entry=True, time_offset_min=10),
    ])
    poller = TradeEventPoller()

    first = poller.poll(gw, since=T0, symbol="WIN$N", magic=0)
    assert len(first) == 1

    # Sem deal novo entre os polls
    second = poller.poll(gw, since=T0, symbol="WIN$N", magic=0)
    assert second == []

    # Adiciona deal novo (ticket maior) → segunda chamada deve pegá-lo
    gw.add_deal(_deal(ticket=106, is_entry=False, reason=DEAL_REASON_TP,
                      time_offset_min=30))
    third = poller.poll(gw, since=T0, symbol="WIN$N", magic=0)
    assert len(third) == 1
    assert third[0].deal.ticket == 106


#+------------------------------------------------------------------+
#| 7. Filtro por symbol                                            |
#+------------------------------------------------------------------+
def test_poller_filtra_por_symbol():
    gw = _FakeGatewayWithDeals([
        _deal(ticket=110, symbol="WIN$N", is_entry=True, time_offset_min=10),
        _deal(ticket=111, symbol="WDO$N", is_entry=True, time_offset_min=11),
    ])
    poller = TradeEventPoller()

    events = poller.poll(gw, since=T0, symbol="WIN$N", magic=0)

    assert len(events) == 1
    assert events[0].deal.ticket == 110


#+------------------------------------------------------------------+
#| 8. Filtro por magic                                             |
#+------------------------------------------------------------------+
def test_poller_filtra_por_magic():
    gw = _FakeGatewayWithDeals([
        _deal(ticket=120, magic=20260718, is_entry=True, time_offset_min=10),
        _deal(ticket=121, magic=99999, is_entry=True, time_offset_min=11),
    ])
    poller = TradeEventPoller()

    events = poller.poll(gw, since=T0, symbol="WIN$N", magic=20260718)

    assert len(events) == 1
    assert events[0].deal.ticket == 120


#+------------------------------------------------------------------+
#| 9. Múltiplos deals na mesma poll — ordem preservada              |
#+------------------------------------------------------------------+
def test_poller_multiplos_deals_em_ordem():
    gw = _FakeGatewayWithDeals([
        _deal(ticket=130, is_entry=True, time_offset_min=10),
        _deal(ticket=131, is_entry=False, reason=DEAL_REASON_TP, time_offset_min=20),
        _deal(ticket=132, is_entry=True, time_offset_min=30),
    ])
    poller = TradeEventPoller()

    events = poller.poll(gw, since=T0, symbol="WIN$N", magic=0)

    assert len(events) == 3
    assert isinstance(events[0], EntryFilled)
    assert isinstance(events[1], TakeProfitHit)
    assert isinstance(events[2], EntryFilled)
    # Ordem por ticket é preservada
    assert [e.deal.ticket for e in events] == [130, 131, 132]


#+------------------------------------------------------------------+
#| 10. Integração: FakeGateway + RealExecutor + TradeEventPoller    |
#+------------------------------------------------------------------+
def test_poller_integracao_com_fake_gateway():
    """Simula o fluxo: executor coloca ordem → FakeGateway gera deal →
    poller captura EntryFilled."""
    from engine.application.executor import RealExecutor
    from engine.application.intent import TradeIntent
    from engine.config.presets import StdDevV510Preset
    from engine.domain.strategy.location import RegionState, TradeLocation

    # Mock de um TradeIntent simples
    loc = TradeLocation(
        bar_time=T0, high=1200.0, low=1000.0, volume=5000.0, big_candle=False,
    )
    region = RegionState(location=loc)
    region.phase = region.phase.BROKEN
    region.is_buy = True
    region.stop_loss = 800.0
    region.take_profit = 1700.0

    intent = TradeIntent(
        region=region,
        is_buy=True,
        entry_price=1100.0,
        stop_loss=800.0,
        take_profit=1700.0,
        volume=0.0,
        as_pending=False,
        reason="test",
        created_at=T0,
    )

    gw = FakeGateway()
    gw.connect()

    preset = StdDevV510Preset.model_validate({
        "name": "test", "strategy": "stddev_v510",
    })
    executor = RealExecutor(gw, preset)
    result = executor.execute(intent, symbol="WIN$N")
    assert result.is_ok

    # Poller lê history_deals do fake
    poller = TradeEventPoller()
    events = poller.poll(gw, since=T0, symbol="WIN$N", magic=0)

    assert len(events) == 1
    assert isinstance(events[0], EntryFilled)
    assert events[0].deal.volume == 6.0