"""Golden tests do RealExecutor contra FakeGateway (F3a)."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta

import pytest

from engine.application.executor import RealExecutor
from engine.application.trading_session import TradingSession
from engine.config.presets import (
    EntryLevelMode,
    EntryParams,
    SessionParams,
    StdDevV510Preset,
    TimeWindowParams,
)
from engine.domain.shared.types import Bar, MarketSnapshot
from engine.infrastructure.mt5.fake import FakeGateway

T0 = datetime(2026, 10, 29, 9, 0)
TICK = timedelta(minutes=1)
SYMBOL = "WIN$N"


#+------------------------------------------------------------------+
#| Helpers                                                          |
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
#| 1. Market order — abre posição imediatamente                    |
#+------------------------------------------------------------------+
def test_executor_market_abre_posicao_no_fake():
    gw, executor, _ = _executor()
    _, intent = _build_intent()
    intent = replace(intent, as_pending=False)

    result = executor.execute(intent, symbol=SYMBOL)

    assert result.ok is True
    assert result.volume == 6.0   # 6 contratos × 1.0 lot_per_contract
    assert result.order_result.retcode == 10009
    assert len(gw.positions(SYMBOL)) == 1


#+------------------------------------------------------------------+
#| 2. Limit order — registra pendente, sem posição                 |
#+------------------------------------------------------------------+
def test_executor_limit_registra_pendente_no_fake():
    gw, executor, _ = _executor()
    _, intent = _build_intent()
    intent = replace(intent, as_pending=True)

    result = executor.execute(intent, symbol=SYMBOL)

    assert result.ok is True
    assert len(gw.orders(SYMBOL)) == 1
    assert len(gw.positions(SYMBOL)) == 0


#+------------------------------------------------------------------+
#| 3. Pendente pode ser preenchida manualmente                     |
#+------------------------------------------------------------------+
def test_executor_fill_pendente_manual():
    gw, executor, _ = _executor()
    _, intent = _build_intent()
    intent = replace(intent, as_pending=True)

    result = executor.execute(intent, symbol=SYMBOL)
    ticket = result.order_result.order_ticket
    gw._force_fill_pending(ticket)

    assert len(gw.positions(SYMBOL)) == 1
    assert len(gw.orders(SYMBOL)) == 0


#+------------------------------------------------------------------+
#| 4. Cancel — remove pendente                                     |
#+------------------------------------------------------------------+
def test_executor_cancel_pendente():
    gw, executor, _ = _executor()
    _, intent = _build_intent()
    intent = replace(intent, as_pending=True)

    result = executor.execute(intent, symbol=SYMBOL)
    ticket = result.order_result.order_ticket
    cancel_result = executor.cancel(ticket)

    assert cancel_result.is_ok
    assert len(gw.orders(SYMBOL)) == 0


#+------------------------------------------------------------------+
#| 5. Close — fecha posição                                        |
#+------------------------------------------------------------------+
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


#+------------------------------------------------------------------+
#| 6. Modify — altera SL/TP                                        |
#+------------------------------------------------------------------+
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


#+------------------------------------------------------------------+
#| 7. Volume com lot_min respeitado (sanity do _normalize_lot)     |
#+------------------------------------------------------------------+
def test_executor_respeita_lot_min_do_simbolo():
    gw, _, preset = _executor()
    # Força total_contracts=0 pra violar o mínimo
    from engine.config.presets import RiskParams
    preset_min = StdDevV510Preset.model_validate({
        **preset.model_dump(mode="json"),
        "risk": RiskParams(total_contracts=1, lot_per_contract=0.01).model_dump(),
    })
    executor = RealExecutor(gw, preset_min)

    _, intent = _build_intent()
    intent = replace(intent, as_pending=False)
    result = executor.execute(intent, symbol=SYMBOL)

    assert result.ok
    # lots_min do FakeGateway é 1.0 → volume deve ser >= 1.0
    assert result.volume >= 1.0