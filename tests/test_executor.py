"""Golden tests do RealExecutor contra FakeGateway (F3a + F5b)."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta

import pytest

from engine.application.executor import RealExecutor
from engine.application.trading_session import TradingSession
from engine.config.presets import (
    DetectorParams,
    EntryLevelMode,
    EntryParams,
    RiskParams,
    SessionParams,
    SizingMode,
    StdDevV510Preset,
    TimeWindowParams,
)
from engine.domain.shared.types import Bar, MarketSnapshot
from engine.infrastructure.mt5.fake import FakeGateway

T0 = datetime(2026, 10, 29, 9, 0)
TICK = timedelta(minutes=1)
SYMBOL = "WIN$N"


#+------------------------------------------------------------------+
#| Helpers gerais                                                   |
#+------------------------------------------------------------------+
def _bar(now: datetime, high: float, low: float, vol: float) -> Bar:
    mid = (high + low) / 2
    return Bar(
        time=now, open=mid, high=high, low=low, close=mid,
        tick_volume=vol, real_volume=0.0,
    )


def _snap(ask: float, bid: float, now: datetime) -> MarketSnapshot:
    return MarketSnapshot(ask=ask, bid=bid, now=now)


def _preset() -> StdDevV510Preset:
    return StdDevV510Preset.model_validate({
        "name": "test",
        "strategy": "stddev_v510",
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=time(9, 0), end=time(17, 30)),
        ).model_dump(),
        "entry": EntryParams(level_mode=EntryLevelMode.MID).model_dump(),
    })


def _build_intent():
    """Fluxo completo: barra cria região → tick rompe → tick puxa."""
    preset = _preset()
    sess = TradingSession(preset)
    sess.on_bar_closed(
        _bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    sess.on_tick(_snap(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    decision = sess.on_tick(_snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK))
    assert decision.intent is not None
    return preset, decision.intent


def _executor() -> tuple[FakeGateway, RealExecutor, StdDevV510Preset]:
    preset, _ = _build_intent()
    gw = FakeGateway()
    gw.connect()
    return gw, RealExecutor(gw, preset), preset


#+------------------------------------------------------------------+
#| F3a — Execução básica                                            |
#+------------------------------------------------------------------+
def test_executor_market_abre_posicao_no_fake():
    gw, executor, _ = _executor()
    _, intent = _build_intent()
    intent = replace(intent, as_pending=False)

    result = executor.execute(intent, symbol=SYMBOL)

    assert result.is_ok is True
    assert result.volume == 6.0
    assert result.order_result.retcode == 10009
    assert len(gw.positions(SYMBOL)) == 1


def test_executor_limit_registra_pendente_no_fake():
    gw, executor, _ = _executor()
    _, intent = _build_intent()
    intent = replace(intent, as_pending=True)

    result = executor.execute(intent, symbol=SYMBOL)

    assert result.is_ok is True
    assert len(gw.orders(SYMBOL)) == 1
    assert len(gw.positions(SYMBOL)) == 0


def test_executor_fill_pendente_manual():
    gw, executor, _ = _executor()
    _, intent = _build_intent()
    intent = replace(intent, as_pending=True)

    result = executor.execute(intent, symbol=SYMBOL)
    ticket = result.order_result.order_ticket
    gw._force_fill_pending(ticket)

    assert len(gw.positions(SYMBOL)) == 1
    assert len(gw.orders(SYMBOL)) == 0


def test_executor_cancel_pendente():
    gw, executor, _ = _executor()
    _, intent = _build_intent()
    intent = replace(intent, as_pending=True)

    result = executor.execute(intent, symbol=SYMBOL)
    ticket = result.order_result.order_ticket
    cancel_result = executor.cancel(ticket)

    assert cancel_result.is_ok
    assert len(gw.orders(SYMBOL)) == 0


def test_executor_close_posicao():
    gw, executor, _ = _executor()
    _, intent = _build_intent()
    intent = replace(intent, as_pending=False)

    result = executor.execute(intent, symbol=SYMBOL)
    ticket = result.order_result.order_ticket
    assert len(gw.positions(SYMBOL)) == 1

    close_result = executor.close(ticket)
    assert close_result.is_ok
    assert len(gw.positions(SYMBOL)) == 0


def test_executor_modify_sl_tp():
    gw, executor, _ = _executor()
    _, intent = _build_intent()
    intent = replace(intent, as_pending=False)

    result = executor.execute(intent, symbol=SYMBOL)
    ticket = result.order_result.order_ticket
    modify_result = executor.modify(ticket, stop_loss=1050.0, take_profit=1300.0)

    assert modify_result.is_ok
    positions = gw.positions(SYMBOL)
    assert positions[0].stop_loss == 1050.0
    assert positions[0].take_profit == 1300.0


def test_executor_respeita_lot_min_do_simbolo():
    gw, _, preset = _executor()
    preset_min = StdDevV510Preset.model_validate({
        **preset.model_dump(mode="json"),
        "risk": RiskParams(total_contracts=1, lot_per_contract=0.01).model_dump(),
    })
    executor = RealExecutor(gw, preset_min)

    _, intent = _build_intent()
    intent = replace(intent, as_pending=False)
    result = executor.execute(intent, symbol=SYMBOL)

    assert result.is_ok
    assert result.volume >= 1.0


#+------------------------------------------------------------------+
#| F5b — By-risk sizing                                             |
#+------------------------------------------------------------------+
def _preset_by_risk(
    *,
    risk_mode="fixed_money",
    risk_value=500.0,
    total_contracts=100,
    lot_per_contract=1.0,
) -> StdDevV510Preset:
    """Preset com SIZING_BY_RISK (para os testes de F5b)."""
    return StdDevV510Preset.model_validate({
        "name": "test_by_risk",
        "strategy": "stddev_v510",
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=time(9, 0), end=time(17, 30)),
        ).model_dump(),
        "entry": EntryParams(level_mode=EntryLevelMode.MID, as_pending=False).model_dump(),
        "risk": RiskParams(
            sizing_mode=SizingMode.BY_RISK,
            risk_mode=risk_mode,
            risk_value=risk_value,
            total_contracts=total_contracts,
            lot_per_contract=lot_per_contract,
        ).model_dump(),
    })


def _build_intent_com_sl(sl_dist: float = 200.0):
    """Constrói um TradeIntent e FORÇA o SL = entry - sl_dist (compra)."""
    preset = _preset()
    sess = TradingSession(preset)
    sess.on_bar_closed(
        _bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    sess.on_tick(_snap(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    decision = sess.on_tick(_snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK))
    assert decision.intent is not None
    # FORÇA o SL para o valor que o teste quer (a sessão calculou 800)
    return replace(decision.intent, stop_loss=decision.intent.entry_price - sl_dist)


def test_by_risk_fixed_money():
    """risk_value=500, sl_dist=200, tick_size=1, tick_value=1 → lot=2.5→2.0."""
    preset = _preset_by_risk(risk_mode="fixed_money", risk_value=500.0)
    gw = FakeGateway()
    gw.connect()
    executor = RealExecutor(gw, preset)

    intent = _build_intent_com_sl(sl_dist=200.0)
    result = executor.execute(intent, symbol=SYMBOL)

    assert result.is_ok
    assert result.volume == 2.0


def test_by_risk_percent_balance():
    """balance=100k, risk_value=1%, sl_dist=200 → 1000/200 = 5.0 lotes."""
    preset = _preset_by_risk(risk_mode="percent_balance", risk_value=1.0)
    gw = FakeGateway()
    gw.connect()
    executor = RealExecutor(gw, preset)

    intent = _build_intent_com_sl(sl_dist=200.0)
    result = executor.execute(intent, symbol=SYMBOL)

    assert result.is_ok
    assert result.volume == 5.0


def test_by_risk_respeita_lots_min():
    """sl_dist enorme → lot calculado cai abaixo de lots_min → volta lots_min."""
    preset = _preset_by_risk(risk_mode="fixed_money", risk_value=100.0)
    gw = FakeGateway()
    gw.connect()
    executor = RealExecutor(gw, preset)

    intent = _build_intent_com_sl(sl_dist=10000.0)
    result = executor.execute(intent, symbol=SYMBOL)

    assert result.is_ok
    assert result.volume == 1.0


def test_by_risk_sl_dist_zero_usa_lots_min():
    """Se entry == stop_loss, usa lots_min (fallback conservador)."""
    preset = _preset_by_risk(risk_mode="fixed_money", risk_value=500.0)
    gw = FakeGateway()
    gw.connect()
    executor = RealExecutor(gw, preset)

    intent = _build_intent_com_sl(sl_dist=200.0)
    intent = replace(intent, stop_loss=intent.entry_price)

    result = executor.execute(intent, symbol=SYMBOL)

    assert result.is_ok
    assert result.volume == 1.0


def test_by_risk_ignora_total_contracts():
    """total_contracts=100 mas by_risk calcula pelo risco (2.5→2.0)."""
    preset = _preset_by_risk(
        risk_mode="fixed_money", risk_value=500.0,
        total_contracts=100,
    )
    gw = FakeGateway()
    gw.connect()
    executor = RealExecutor(gw, preset)

    intent = _build_intent_com_sl(sl_dist=200.0)
    result = executor.execute(intent, symbol=SYMBOL)

    assert result.is_ok
    assert result.volume == 2.0



#+------------------------------------------------------------------+
#| F5e — OrderRequest.is_stop                                      |
#+------------------------------------------------------------------+
def test_order_request_is_stop_default_false():
    """OrderRequest padrão: is_stop=False (market/limit)."""
    from engine.infrastructure.mt5.gateway import OrderRequest
    req = OrderRequest(
        symbol="WIN$N", is_buy=True, volume=1.0, price=1000.0,
        is_limit=False,
    )
    assert req.is_stop is False


def test_fake_gateway_is_stop_registra_ordem_nao_posicao():
    """is_stop=True → ordem pendente (não abre posição)."""
    from engine.infrastructure.mt5.fake import FakeGateway
    from engine.infrastructure.mt5.gateway import OrderRequest

    gw = FakeGateway()
    gw.connect()
    req = OrderRequest(
        symbol="WIN$N", is_buy=False, volume=1.0, price=900.0,
        is_limit=False, is_stop=True, comment="test_stop",
    )
    res = gw.place_order(req)

    assert res.is_ok
    assert len(gw.orders("WIN$N")) == 1
    assert len(gw.positions("WIN$N")) == 0