"""Golden tests do ShadowComparer (F4)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.application.shadow import ShadowComparer
from engine.application.shadow_report import Divergence, ShadowReport
from engine.infrastructure.mt5.gateway import DealInfo

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
TICK = timedelta(minutes=1)


def _deal(
    *, ticket: int, bar_time: datetime, is_buy: bool, price: float,
    is_entry: bool = True, magic: int = 20260718,
) -> DealInfo:
    return DealInfo(
        ticket=ticket, order_ticket=ticket, position_ticket=ticket + 1000,
        symbol="WIN$N", is_buy=is_buy, volume=6.0, price=price,
        is_entry=is_entry, magic=magic, comment="",
        time=bar_time, reason=0,
    )


def _py_trade(*, bar_time: datetime, is_buy: bool, price: float):
    """Constrói um TradeIntent mínimo para os testes."""
    from engine.application.intent import TradeIntent
    from engine.domain.strategy.location import RegionState, TradeLocation

    loc = TradeLocation(
        bar_time=bar_time, high=price + 100, low=price - 100,
        volume=5000.0, big_candle=False,
    )
    region = RegionState(location=loc)
    region.phase = region.phase.BROKEN
    region.is_buy = is_buy
    region.stop_loss = price - 200 if is_buy else price + 200
    region.take_profit = price + 600 if is_buy else price - 600

    return TradeIntent(
        region=region, is_buy=is_buy, entry_price=price,
        stop_loss=region.stop_loss, take_profit=region.take_profit,
        volume=6.0, as_pending=True, reason="pullback",
        created_at=bar_time,
    )


#+------------------------------------------------------------------+
#| 1. Caso perfeito — todos batem                                 |
#+------------------------------------------------------------------+
def test_shadow_perfeito():
    ea = [
        _deal(ticket=1, bar_time=T0, is_buy=True, price=1100.0),
        _deal(ticket=2, bar_time=T0 + 5 * TICK, is_buy=False, price=1200.0),
    ]
    py = [
        _py_trade(bar_time=T0, is_buy=True, price=1100.0),
        _py_trade(bar_time=T0 + 5 * TICK, is_buy=False, price=1200.0),
    ]
    rep = ShadowComparer().compare(
        ea, py, start=T0, end=T0 + 10 * TICK,
    )
    assert rep.matched == 2
    assert rep.ea_only == 0
    assert rep.py_only == 0
    assert rep.mismatches == 0
    assert rep.match_rate == 1.0


#+------------------------------------------------------------------+
#| 2. Só no EA                                                    |
#+------------------------------------------------------------------+
def test_shadow_ea_only():
    ea = [_deal(ticket=1, bar_time=T0, is_buy=True, price=1100.0)]
    rep = ShadowComparer().compare(
        ea, [], start=T0, end=T0 + 10 * TICK,
    )
    assert rep.matched == 0
    assert rep.ea_only == 1
    assert rep.py_only == 0
    assert rep.total_ea == 1
    assert len(rep.divergences) == 1
    assert rep.divergences[0].kind == "ea_only"


#+------------------------------------------------------------------+
#| 3. Só no Python                                                |
#+------------------------------------------------------------------+
def test_shadow_py_only():
    py = [_py_trade(bar_time=T0, is_buy=True, price=1100.0)]
    rep = ShadowComparer().compare(
        [], py, start=T0, end=T0 + 10 * TICK,
    )
    assert rep.matched == 0
    assert rep.ea_only == 0
    assert rep.py_only == 1
    assert rep.total_py == 1


#+------------------------------------------------------------------+
#| 4. Mismatch de preço                                           |
#+------------------------------------------------------------------+
def test_shadow_mismatch_de_preco():
    ea = [_deal(ticket=1, bar_time=T0, is_buy=True, price=1100.0)]
    py = [_py_trade(bar_time=T0, is_buy=True, price=1150.0)]  # 50 pts diff
    rep = ShadowComparer().compare(
        ea, py, start=T0, end=T0 + 10 * TICK, tolerance_points=2.0,
    )
    assert rep.matched == 0
    assert rep.mismatches == 1
    assert len(rep.divergences) == 1
    assert rep.divergences[0].kind == "mismatch"


#+------------------------------------------------------------------+
#| 5. Match dentro da tolerância                                  |
#+------------------------------------------------------------------+
def test_shadow_match_dentro_da_tolerancia():
    ea = [_deal(ticket=1, bar_time=T0, is_buy=True, price=1100.0)]
    py = [_py_trade(bar_time=T0, is_buy=True, price=1101.5)]  # 1.5 pts diff
    rep = ShadowComparer().compare(
        ea, py, start=T0, end=T0 + 10 * TICK, tolerance_points=2.0,
    )
    assert rep.matched == 1
    assert rep.mismatches == 0
    assert rep.match_rate == 1.0


#+------------------------------------------------------------------+
#| 6. Deals de saída são ignorados                                |
#+------------------------------------------------------------------+
def test_shadow_ignora_deals_de_saida():
    ea_entry = _deal(ticket=1, bar_time=T0, is_buy=True, price=1100.0)
    ea_exit = _deal(ticket=2, bar_time=T0 + TICK, is_buy=True,
                    price=1100.0, is_entry=False)
    rep = ShadowComparer().compare(
        [ea_entry, ea_exit], [],
        start=T0, end=T0 + 10 * TICK,
    )
    assert rep.ea_only == 1  # só a entrada conta