"""Golden tests do simulador F6-lite."""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest

from engine.application.events import BarEvent, EventFeed, TickEvent
from engine.application.simulation import (
    ExitReason,
    SimulatedExecutor,
    run_simulation,
)
from engine.config.presets import (
    EntryLevelMode,
    EntryParams,
    SessionParams,
    StdDevV510Preset,
    TimeWindowParams,
)
from engine.domain.shared.types import Bar, MarketSnapshot

T0 = datetime(2026, 10, 29, 9, 0)
TICK = timedelta(minutes=1)


def _bar(now: datetime, high: float, low: float, vol: float) -> Bar:
    mid = (high + low) / 2
    return Bar(time=now, open=mid, high=high, low=low, close=mid,
               tick_volume=vol, real_volume=0.0)


def _snap(ask: float, bid: float, now: datetime) -> MarketSnapshot:
    return MarketSnapshot(ask=ask, bid=bid, now=now)


def _preset(**overrides) -> StdDevV510Preset:
    base = {
        "name": "test",
        "strategy": "stddev_v510",
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=time(9, 0), end=time(17, 30)),
        ).model_dump(),
        "entry": EntryParams(level_mode=EntryLevelMode.MID).model_dump(),
    }
    base.update(overrides)
    return StdDevV510Preset.model_validate(base)


def _make_feed(events: list) -> EventFeed:
    return EventFeed(events)


#+------------------------------------------------------------------+
#| Executor: fill imediato (as_pending=False)                       |
#+------------------------------------------------------------------+
def test_executor_fill_market_abre_trade():
    preset = _preset()
    executor = SimulatedExecutor(preset)
    # Cria uma intent "manual" (sem sessão) — usando o próprio TradingSession
    from engine.application.trading_session import TradingSession
    sess = TradingSession(preset)
    sess.on_bar_closed(
        bar=_bar(T0 + 10 * TICK, high=1200.0, low=1000.0, vol=5000.0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    # Rompe
    sess.on_tick(_snap(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    # Pullback
    decision = sess.on_tick(_snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK))
    assert decision.intent is not None

    # Executor com as_pending=False (força fill imediato)
    from dataclasses import replace
    intent = replace(decision.intent, as_pending=False)
    executor.execute(intent, _snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK))
    assert executor.open_trade is not None
    assert executor.open_trade.entry_price == 1100.0


#+------------------------------------------------------------------+
#| Executor: SL hit                                                 |
#+------------------------------------------------------------------+
def test_executor_sl_hit_fecha_trade():
    preset = _preset()
    executor = SimulatedExecutor(preset)

    from engine.application.trading_session import TradingSession
    from dataclasses import replace
    sess = TradingSession(preset)
    sess.on_bar_closed(_bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0),
                        zscore=5.0, now=T0 + 10 * TICK)
    sess.on_tick(_snap(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    decision = sess.on_tick(_snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK))
    assert decision.intent is not None
    intent = replace(decision.intent, as_pending=False)
    executor.execute(intent, _snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK))

    # Preço cai até SL (800 para compra)
    executor.on_tick(_snap(ask=799.0, bid=798.0, now=T0 + 13 * TICK))
    trades = executor.trades
    assert len(trades) == 1
    assert trades[0].exit_reason == ExitReason.STOP_LOSS
    assert trades[0].pnl_money < 0  # loss


#+------------------------------------------------------------------+
#| Executor: TP hit                                                 |
#+------------------------------------------------------------------+
def test_executor_tp_hit_fecha_trade_com_lucro():
    preset = _preset()
    executor = SimulatedExecutor(preset)

    from engine.application.trading_session import TradingSession
    from dataclasses import replace
    sess = TradingSession(preset)
    sess.on_bar_closed(_bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0),
                        zscore=5.0, now=T0 + 10 * TICK)
    sess.on_tick(_snap(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    decision = sess.on_tick(_snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK))
    intent = replace(decision.intent, as_pending=False)
    executor.execute(intent, _snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK))

    # Preço sobe até TP (1700 para compra)
    executor.on_tick(_snap(ask=1701.0, bid=1700.0, now=T0 + 13 * TICK))
    trades = executor.trades
    assert len(trades) == 1
    assert trades[0].exit_reason == ExitReason.TAKE_PROFIT
    assert trades[0].pnl_money > 0  # profit


#+------------------------------------------------------------------+
#| Executor: SL ganha empate                                        |
#+------------------------------------------------------------------+
def test_executor_sl_ganha_empate_no_mesmo_tick():
    """Se ask cobre TP E bid cobre SL no mesmo tick, SL ganha."""
    preset = _preset()
    executor = SimulatedExecutor(preset)

    from engine.application.trading_session import TradingSession
    from dataclasses import replace
    sess = TradingSession(preset)
    sess.on_bar_closed(_bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0),
                        zscore=5.0, now=T0 + 10 * TICK)
    sess.on_tick(_snap(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    decision = sess.on_tick(_snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK))
    intent = replace(decision.intent, as_pending=False)
    executor.execute(intent, _snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK))

    # Tick malicioso: ask > TP E bid < SL ao mesmo tempo (impossível na vida
    # real, mas testa a regra "SL ganha")
    executor.on_tick(_snap(ask=1800.0, bid=700.0, now=T0 + 13 * TICK))
    trades = executor.trades
    assert len(trades) == 1
    assert trades[0].exit_reason == ExitReason.STOP_LOSS  # SL ganhou


#+------------------------------------------------------------------+
#| End-to-end: run_simulation                                       |
#+------------------------------------------------------------------+
def test_run_simulation_simples_compra_ate_tp():
    """Cenário: barra cria região, tick rompe, tick puxa, tick sobe até TP."""
    preset = _preset()
    bar = _bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0)

    events = [
        BarEvent(bar=bar, zscore=5.0),
        TickEvent(_snap(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK)),
        TickEvent(_snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK)),
        TickEvent(_snap(ask=1701.0, bid=1700.0, now=T0 + 13 * TICK)),
    ]
    result = run_simulation(_make_feed(events), preset)

    assert result.stats["n_trades"] == 1
    assert result.stats["winners"] == 1
    assert result.trades[0].exit_reason == ExitReason.TAKE_PROFIT
    # Entrada 1100, saída 1700 → 600 pontos × 6 contratos = 3600
    assert result.trades[0].pnl_points == pytest.approx(600.0 * 6.0)


def test_run_simulation_sem_eventos_retorna_vazio():
    preset = _preset()
    result = run_simulation(_make_feed([]), preset)
    assert result.stats["n_trades"] == 0
    assert result.stats["total_pnl_money"] == 0.0


#+------------------------------------------------------------------+
#| EventFeed — sanity                                               |
#+------------------------------------------------------------------+
def test_event_feed_fora_de_ordem_rejeitado():
    bar = _bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0)
    with pytest.raises(ValueError, match="fora de ordem"):
        EventFeed([
            BarEvent(bar=bar, zscore=5.0),
            TickEvent(_snap(1000, 999, T0 + 5 * TICK)),  # antes da barra
        ])