"""Golden tests do PartialSpec, make_partial_specs e integração (F5a)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine.application.executor import RealExecutor
from engine.application.intent import TradeIntent
from engine.application.partial_spec import PartialSpec, make_partial_specs
from engine.application.poller import TradeEventPoller
from engine.application.trade_events import PartialFilled
from engine.application.trading_session import TradingSession
from engine.config.presets import (
    DetectorParams,
    EntryParams,
    PartialExitType,
    PartialTier,
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


#+------------------------------------------------------------------+
#| PartialSpec.target_price                                         |
#+------------------------------------------------------------------+
def test_target_price_compra_por_pontos():
    spec = PartialSpec(tier_index=0, contracts=3, points=200.0)
    assert spec.target_price(1000.0, is_buy=True,
                              exit_type=PartialExitType.POINTS) == 1200.0


def test_target_price_venda_por_pontos():
    spec = PartialSpec(tier_index=0, contracts=3, points=200.0)
    assert spec.target_price(1000.0, is_buy=False,
                              exit_type=PartialExitType.POINTS) == 800.0


def test_target_price_compra_por_percentual():
    spec = PartialSpec(tier_index=0, contracts=3, points=0.0, percent=0.5)
    assert spec.target_price(1000.0, is_buy=True,
                              exit_type=PartialExitType.PERCENT) == 1005.0


def test_target_price_venda_por_percentual():
    spec = PartialSpec(tier_index=0, contracts=3, points=0.0, percent=0.5)
    assert spec.target_price(1000.0, is_buy=False,
                              exit_type=PartialExitType.PERCENT) == 995.0


#+------------------------------------------------------------------+
#| Validações                                                       |
#+------------------------------------------------------------------+
def test_spec_rejeita_tier_index_negativo():
    with pytest.raises(ValueError, match="tier_index"):
        PartialSpec(tier_index=-1, contracts=3, points=200.0)


def test_spec_rejeita_contracts_negativo():
    with pytest.raises(ValueError, match="contracts"):
        PartialSpec(tier_index=0, contracts=-1, points=200.0)


def test_spec_enabled():
    assert PartialSpec(tier_index=0, contracts=3, points=200.0).enabled is True
    assert PartialSpec(tier_index=0, contracts=0, points=200.0).enabled is False


#+------------------------------------------------------------------+
#| make_partial_specs — do preset                                    |
#+------------------------------------------------------------------+
def test_make_specs_desligado_retorna_none():
    specs = make_partial_specs(
        use_partial_exit=False,
        tiers=[PartialTier(contracts=3, points=200.0)],
        exit_type=PartialExitType.POINTS,
        partial_points=200.0,
        partial_percent=0.2,
    )
    assert specs is None


def test_make_specs_so_tier1():
    specs = make_partial_specs(
        use_partial_exit=True,
        tiers=[
            PartialTier(contracts=3, points=200.0),
            PartialTier(contracts=0, points=400.0),
            PartialTier(contracts=0, points=600.0),
        ],
        exit_type=PartialExitType.POINTS,
        partial_points=200.0,
        partial_percent=0.2,
    )
    assert specs is not None
    assert len(specs) == 1
    assert specs[0].tier_index == 0
    assert specs[0].contracts == 3
    assert specs[0].points == 200.0


def test_make_specs_todos_os_tiers():
    specs = make_partial_specs(
        use_partial_exit=True,
        tiers=[
            PartialTier(contracts=2, points=200.0),
            PartialTier(contracts=2, points=400.0),
            PartialTier(contracts=1, points=600.0),
        ],
        exit_type=PartialExitType.POINTS,
        partial_points=200.0,
        partial_percent=0.2,
    )
    assert specs is not None
    assert len(specs) == 3
    assert [s.tier_index for s in specs] == [0, 1, 2]
    assert [s.contracts for s in specs] == [2, 2, 1]
    assert [s.points for s in specs] == [200.0, 400.0, 600.0]


def test_make_specs_tier1_usa_global_nao_o_do_tier():
    specs = make_partial_specs(
        use_partial_exit=True,
        tiers=[PartialTier(contracts=3, points=999.0)],
        exit_type=PartialExitType.POINTS,
        partial_points=200.0,
        partial_percent=0.2,
    )
    assert specs is not None
    assert specs[0].points == 200.0


def test_make_specs_tudo_zerado_retorna_none():
    specs = make_partial_specs(
        use_partial_exit=True,
        tiers=[
            PartialTier(contracts=0, points=200.0),
            PartialTier(contracts=0, points=400.0),
        ],
        exit_type=PartialExitType.POINTS,
        partial_points=200.0,
        partial_percent=0.2,
    )
    assert specs is None


#+------------------------------------------------------------------+
#| Integração: TradeIntent.partials + Executor + Session + Poller   |
#+------------------------------------------------------------------+
def _preset_com_parciais() -> StdDevV510Preset:
    """Preset com parciais LIGADAS (3 tiers: 2@200, 2@400, 1@600)."""
    return StdDevV510Preset.model_validate({
        "name": "test",
        "strategy": "stddev_v510",
        "detector": DetectorParams(mute_open_min=0).model_dump(),
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=__import__("datetime").time(9, 0),
                                    end=__import__("datetime").time(17, 30)),
        ).model_dump(),
        "entry": EntryParams(as_pending=False).model_dump(),
        "risk": RiskParams(
            use_partial_exit=True,
            total_contracts=6,
            partial_as_pending=True,
            exit_type=PartialExitType.POINTS,
            partial_points=200.0,
            tiers=[
                PartialTier(contracts=2, points=200.0),
                PartialTier(contracts=2, points=400.0),
                PartialTier(contracts=1, points=600.0),
            ],
        ).model_dump(),
    })


def _build_intent_com_parciais():
    """Cria uma região, rompe, pullback, e monta o TradeIntent via _make_intent."""
    preset = _preset_com_parciais()
    sess = TradingSession(preset)
    sess.on_bar_closed(
        Bar(time=T0 + 10 * TICK, open=1100, high=1200, low=1000, close=1100,
            tick_volume=5000, real_volume=0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    sess.on_tick(MarketSnapshot(ask=1210, bid=1205, now=T0 + 11 * TICK))
    decision = sess.on_tick(MarketSnapshot(ask=1100, bid=1099, now=T0 + 12 * TICK))
    assert decision.intent is not None
    return preset, sess, decision.intent


#+------------------------------------------------------------------+
#| 13. TradeIntent carrega partials                                |
#+------------------------------------------------------------------+
def test_trade_intent_carrega_partials():
    _, _, intent = _build_intent_com_parciais()
    assert intent.partials is not None
    assert len(intent.partials) == 3
    assert [p.tier_index for p in intent.partials] == [0, 1, 2]
    assert [p.contracts for p in intent.partials] == [2, 2, 1]


#+------------------------------------------------------------------+
#| 14. place_partial_orders arma N ordens limite                   |
#+------------------------------------------------------------------+
def test_place_partial_orders_arma_3_ordens():
    preset, _, intent = _build_intent_com_parciais()
    gw = FakeGateway()
    gw.connect()
    executor = RealExecutor(gw, preset)

    results = executor.place_partial_orders(intent, symbol="WIN$N")

    assert len(results) == 3
    assert all(r.is_ok for r in results)
    orders = gw.orders("WIN$N")
    assert len(orders) == 3
    comments = sorted(o.comment for o in orders)
    assert comments == ["engine_partial_1", "engine_partial_2", "engine_partial_3"]


#+------------------------------------------------------------------+
#| 15. Preço-alvo das parciais está correto                        |
#+------------------------------------------------------------------+
def test_place_partial_orders_preco_alvo():
    preset, _, intent = _build_intent_com_parciais()
    gw = FakeGateway()
    gw.connect()
    executor = RealExecutor(gw, preset)

    executor.place_partial_orders(intent, symbol="WIN$N")
    orders = sorted(gw.orders("WIN$N"), key=lambda o: o.price)

    prices = [o.price for o in orders]
    assert prices == [1300.0, 1500.0, 1700.0]


#+------------------------------------------------------------------+
#| 16. PartialFilled atualiza _partials_filled                     |
#+------------------------------------------------------------------+
def test_on_trade_event_partial_filled_rastreia_tier():
    preset = _preset_com_parciais()
    sess = TradingSession(preset)

    sess.notify_trade_opened(now=T0 + 12 * TICK,
                              region_bar_time=T0 + 10 * TICK)
    assert sess.partials_filled == []

    deal = DealInfo(
        ticket=1000, order_ticket=1000, position_ticket=5000,
        symbol="WIN$N", is_buy=False, volume=2.0, price=1300.0,
        is_entry=False, magic=0, comment="engine_partial_1",
        time=T0 + 20 * TICK, reason=0,
    )
    ev = PartialFilled(deal=deal, position_ticket=5000, remaining_volume=4.0)
    sess.on_trade_event(ev, now=T0 + 20 * TICK)

    assert sess.partials_filled == [0]


#+------------------------------------------------------------------+
#| 17. Tier 2 e 3 são rastreados na ordem                          |
#+------------------------------------------------------------------+
def test_on_trade_event_partial_filled_varios_tiers():
    preset = _preset_com_parciais()
    sess = TradingSession(preset)
    sess.notify_trade_opened(now=T0 + 12 * TICK,
                              region_bar_time=T0 + 10 * TICK)

    for i in (1, 2, 3):
        deal = DealInfo(
            ticket=1000 + i, order_ticket=1000 + i, position_ticket=5000,
            symbol="WIN$N", is_buy=False, volume=2.0, price=1100.0 + 200 * i,
            is_entry=False, magic=0, comment=f"engine_partial_{i}",
            time=T0 + (20 + i) * TICK, reason=0,
        )
        ev = PartialFilled(deal=deal, position_ticket=5000, remaining_volume=1.0)
        sess.on_trade_event(ev, now=T0 + (20 + i) * TICK)

    assert sess.partials_filled == [0, 1, 2]


#+------------------------------------------------------------------+
#| 18. notify_position_closed zera _partials_filled                |
#+------------------------------------------------------------------+
def test_notify_position_closed_zera_partials_filled():
    preset = _preset_com_parciais()
    sess = TradingSession(preset)
    sess.notify_trade_opened(now=T0 + 12 * TICK,
                              region_bar_time=T0 + 10 * TICK)

    deal = DealInfo(
        ticket=1000, order_ticket=1000, position_ticket=5000,
        symbol="WIN$N", is_buy=False, volume=2.0, price=1300.0,
        is_entry=False, magic=0, comment="engine_partial_1",
        time=T0 + 20 * TICK, reason=0,
    )
    sess.on_trade_event(PartialFilled(deal=deal, position_ticket=5000,
                                       remaining_volume=4.0),
                        now=T0 + 20 * TICK)
    assert sess.partials_filled == [0]

    sess.notify_position_closed(now=T0 + 30 * TICK)
    assert sess.partials_filled == []