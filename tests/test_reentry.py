"""Golden tests do reforço (F5c).

Cobre:
  - _maybe_reentry: armar quando preço avança, emitir quando volta
  - _maybe_reentry: não rearma 2x
  - Executor: place_reentry_order + place_reentry_exits
  - Integração: FakeGateway recebe as ordens certas
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta, timezone

import pytest

from engine.application.executor import RealExecutor
from engine.application.intent import ReentryIntent
from engine.application.trading_session import TradingSession
from engine.application.trade_events import ReentryFilled
from engine.config.presets import (
    DetectorParams,
    EntryLevelMode,
    EntryParams,
    RiskParams,
    SessionParams,
    StdDevV510Preset,
    TimeWindowParams,
)
from engine.domain.shared.types import Bar, MarketSnapshot
from engine.infrastructure.mt5.fake import FakeGateway
from engine.infrastructure.mt5.gateway import DealInfo

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
TICK = timedelta(minutes=1)
SYMBOL = "WIN$N"


def _bar(now: datetime, high: float, low: float, vol: float) -> Bar:
    mid = (high + low) / 2
    return Bar(time=now, open=mid, high=high, low=low, close=mid,
               tick_volume=vol, real_volume=0.0)


def _snap(ask: float, bid: float, now: datetime) -> MarketSnapshot:
    return MarketSnapshot(ask=ask, bid=bid, now=now)


def _preset_com_reentry() -> StdDevV510Preset:
    return StdDevV510Preset.model_validate({
        "name": "test_reentry",
        "strategy": "stddev_v510",
        "detector": DetectorParams(mute_open_min=0).model_dump(),
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=time(9, 0), end=time(17, 30)),
        ).model_dump(),
        "entry": EntryParams(level_mode=EntryLevelMode.MID, as_pending=True).model_dump(),
        "risk": RiskParams(
            use_reentry=True,
            reentry_contracts=3,
            reentry_arm_points=200.0,
            reentry_tp_points=200.0,
            reentry_sl_points=200.0,
        ).model_dump(),
    })


def _sess_com_trade_aberto():
    """Cria sessão com região, rompe, pullback, e simula entrada aberta."""
    preset = _preset_com_reentry()
    sess = TradingSession(preset)
    sess.on_bar_closed(
        _bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    sess.on_tick(_snap(1210.0, 1205.0, T0 + 11 * TICK))
    decision = sess.on_tick(_snap(1100.0, 1099.0, T0 + 12 * TICK))
    assert decision.intent is not None
    sess.notify_trade_opened(
        now=T0 + 12 * TICK,
        region_bar_time=decision.intent.bar_time,
        entry_price=decision.intent.entry_price,
        is_buy=True,
    )
    return sess, preset


#+------------------------------------------------------------------+
#| _maybe_reentry: armar                                            |
#+------------------------------------------------------------------+
def test_reentry_arma_quando_preco_avanca():
    sess, _ = _sess_com_trade_aberto()
    decision = sess.on_tick(_snap(1310.0, 1300.0, T0 + 13 * TICK))
    assert sess.reentry_armed is True
    assert decision.reentry_intent is None


def test_reentry_nao_arma_se_preco_nao_avancou():
    sess, _ = _sess_com_trade_aberto()
    decision = sess.on_tick(_snap(1210.0, 1200.0, T0 + 13 * TICK))
    assert sess.reentry_armed is False
    assert decision.reentry_intent is None


#+------------------------------------------------------------------+
#| _maybe_reentry: emitir quando volta                              |
#+------------------------------------------------------------------+
def test_reentry_emite_intent_quando_preco_volta():
    sess, _ = _sess_com_trade_aberto()
    sess.on_tick(_snap(1310.0, 1300.0, T0 + 13 * TICK))
    assert sess.reentry_armed is True
    decision = sess.on_tick(_snap(1100.0, 1099.0, T0 + 14 * TICK))
    assert decision.reentry_intent is not None
    ri = decision.reentry_intent
    assert ri.entry_price == 1100.0
    assert ri.is_buy is True
    assert ri.contracts == 3
    assert ri.tp_points == 200.0
    assert ri.sl_points == 200.0


def test_reentry_nao_rearma_2x():
    sess, _ = _sess_com_trade_aberto()
    sess.on_tick(_snap(1310.0, 1300.0, T0 + 13 * TICK))
    sess.on_tick(_snap(1100.0, 1099.0, T0 + 14 * TICK))
    assert sess.reentry_done is True
    sess.on_tick(_snap(1310.0, 1300.0, T0 + 15 * TICK))
    assert sess.reentry_armed is False
    decision = sess.on_tick(_snap(1100.0, 1099.0, T0 + 16 * TICK))
    assert decision.reentry_intent is None


#+------------------------------------------------------------------+
#| Executor: place_reentry_order                                    |
#+------------------------------------------------------------------+
def test_executor_place_reentry_order():
    preset = _preset_com_reentry()
    gw = FakeGateway()
    gw.connect()
    executor = RealExecutor(gw, preset)

    res = executor.place_reentry_order(
        symbol=SYMBOL, price=1100.0, is_buy=True, contracts=3,
    )
    assert res.is_ok
    orders = gw.orders(SYMBOL)
    assert len(orders) == 1
    assert orders[0].comment == "engine_reentry"
    assert orders[0].price == 1100.0
    assert orders[0].is_buy is True


#+------------------------------------------------------------------+
#| Executor: place_reentry_exits                                    |
#+------------------------------------------------------------------+
def test_executor_place_reentry_exits():
    preset = _preset_com_reentry()
    gw = FakeGateway()
    gw.connect()
    executor = RealExecutor(gw, preset)

    results = executor.place_reentry_exits(
        symbol=SYMBOL, entry_price=1100.0, is_buy=True,
        contracts=3, tp_points=200.0, sl_points=200.0,
    )
    assert len(results) == 2
    assert all(r.is_ok for r in results)
    orders = gw.orders(SYMBOL)
    assert len(orders) == 2
    comments = sorted(o.comment for o in orders)
    assert comments == ["engine_reentry_sl", "engine_reentry_tp"]
    tp = next(o for o in orders if o.comment == "engine_reentry_tp")
    sl = next(o for o in orders if o.comment == "engine_reentry_sl")
    assert tp.price == 1300.0
    assert sl.price == 900.0