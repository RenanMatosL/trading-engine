"""Golden tests do engine run (F3d).

Todos usam FakeGateway (não tocam em MT5) e --fast (não dormem).
"""
from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone

import pytest

from engine.application.executor import RealExecutor
from engine.application.poller import TradeEventPoller
from engine.application.trading_session import TradingSession
from engine.config.presets import (
    DetectorParams,
    EntryParams,          
    SessionParams,
    StdDevV510Preset,
    TimeWindowParams,
)
from engine.domain.shared.types import Bar, MarketSnapshot
from engine.infrastructure.mt5.fake import FakeGateway
from engine.infrastructure.mt5.gateway import DealInfo
from engine.infrastructure.state.memory_store import InMemoryStateStore

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
TICK = timedelta(minutes=1)


def _preset() -> StdDevV510Preset:
    return StdDevV510Preset.model_validate({
        "name": "test",
        "strategy": "stddev_v510",
        "detector": DetectorParams(mute_open_min=0).model_dump(),
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=time(9, 0), end=time(17, 30)),
        ).model_dump(),
        "entry": EntryParams(as_pending=False).model_dump(),
    })


def _bar(now: datetime, high: float, low: float, vol: float) -> Bar:
    mid = (high + low) / 2
    return Bar(time=now, open=mid, high=high, low=low, close=mid,
               tick_volume=vol, real_volume=0.0)


#+------------------------------------------------------------------+
#| 1. Loop básico com FakeGateway + max_ticks                       |
#+------------------------------------------------------------------+
def test_run_dry_run_max_ticks():
    """Loop roda N iterações e para sem travar."""
    from engine import cli

    args = argparse.Namespace(
        cmd="run", json=False,
        dry_run=True, demo=False, preset=None, db=":memory:",
        poll_interval=0.0, max_ticks=3, fast=True,
    )
    settings = cli.EngineSettings()

    # Monkeypatch para evitar arquivo SQLite real
    import engine.cli as cli_mod
    original_store = cli_mod.SqliteStateStore

    class _InMemoryStoreAdapter:
        def __init__(self, path): self._s = InMemoryStateStore()
        def save_session(self, snap): self._s.save_session(snap)
        def load_session(self): return self._s.load_session()
        def save_regions(self, regs): self._s.save_regions(regs)
        def load_regions(self): return self._s.load_regions()
        def clear(self): self._s.clear()
        def close(self): pass

    cli_mod.SqliteStateStore = _InMemoryStoreAdapter
    try:
        rc = cli.cmd_run(args, settings)
        assert rc == 0
    finally:
        cli_mod.SqliteStateStore = original_store


#+------------------------------------------------------------------+
#| 2. Detecção de novo candle fechado                               |
#+------------------------------------------------------------------+
def test_run_detects_new_bar():
    """Se 2 candles chegam, on_bar_closed é chamado 2×."""
    preset = _preset()
    detector_calls = []

    class _DetectorSpy:
        def __init__(self):
            from engine.domain.strategy.detector import VolumeStdDetector
            self._inner = VolumeStdDetector(
                length=preset.detector.length,
                std_ref=preset.detector.std_ref,
                source=preset.detector.volume_source,
            )
        def on_bar_closed(self, bar):
            detector_calls.append(bar.time)
            return self._inner.on_bar_closed(bar)

    # Simula 2 candles chegando em sequência
    detector = _DetectorSpy()
    bar1 = _bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0)
    bar2 = _bar(T0 + 11 * TICK, 1210.0, 1000.0, 5000.0)

    detector.on_bar_closed(bar1)
    detector.on_bar_closed(bar2)

    assert len(detector_calls) == 2
    assert detector_calls[0] == bar1.time
    assert detector_calls[1] == bar2.time


#+------------------------------------------------------------------+
#| 3. TradeIntent → Executor → posição no FakeGateway               |
#+------------------------------------------------------------------+
def test_run_emit_intent_e_executa():
    """Fluxo: região criada → rompe → pullback → executor abre posição."""
    preset = _preset()
    gw = FakeGateway()
    gw.connect()
    session = TradingSession(preset)
    executor = RealExecutor(gw, preset)

    # 1. Barra cria região
    session.on_bar_closed(
        _bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    # 2. Tick rompe
    session.on_tick(MarketSnapshot(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    # 3. Tick puxa até o mid
    decision = session.on_tick(
        MarketSnapshot(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK),
    )
    assert decision.intent is not None

    # 4. Executor abre posição a mercado (as_pending=False no _preset)
    result = executor.execute(decision.intent, symbol="WIN$N")
    assert result.is_ok
    assert len(gw.positions("WIN$N")) == 1

    session.notify_trade_opened(
        now=T0 + 12 * TICK, region_bar_time=decision.intent.bar_time,
    )
    assert session.trades_today == 1


#+------------------------------------------------------------------+
#| 4. Reação a SL — cooldown ativo                                  |
#+------------------------------------------------------------------+
def test_run_reage_a_sl():
    """on_trade_event(StopLossHit) ativa cooldown."""
    preset = _preset()
    session = TradingSession(preset)

    # Simula trade aberto numa região
    session.on_bar_closed(
        _bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    session.on_tick(MarketSnapshot(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    region = session.regions.governing()
    assert region is not None

    session.notify_trade_opened(
        now=T0 + 12 * TICK, region_bar_time=region.bar_time,
    )

    # Chega SL hit
    deal = DealInfo(
        ticket=999, order_ticket=999, position_ticket=5000,
        symbol="WIN$N", is_buy=True, volume=6.0, price=800.0,
        is_entry=False, magic=0, comment="", time=T0 + 13 * TICK, reason=4,
    )
    from engine.application.trade_events import StopLossHit
    session.on_trade_event(StopLossHit(deal=deal, position_ticket=5000),
                           now=T0 + 13 * TICK)

    # Cooldown ativo: próximo on_tick bloqueia
    decision = session.on_tick(
        MarketSnapshot(ask=1100.0, bid=1099.0, now=T0 + 14 * TICK),
    )
    assert decision.blocked_reason == "cooldown"
    assert session.last_sl_time is not None