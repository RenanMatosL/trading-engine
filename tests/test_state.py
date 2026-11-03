"""Golden tests do StateStore (F3c)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine.domain.state.store import SessionSnapshot
from engine.domain.strategy.location import (
    RegionPhase,
    RegionState,
    TradeLocation,
)
from engine.infrastructure.state.memory_store import InMemoryStateStore

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
TICK = timedelta(minutes=1)


def _mk_region(offset_min: int = 0, phase: RegionPhase = RegionPhase.BROKEN):
    loc = TradeLocation(
        bar_time=T0 + offset_min * TICK,
        high=1200.0, low=1000.0, volume=5000.0, big_candle=False,
    )
    return RegionState(
        location=loc,
        phase=phase,
        is_buy=True,
        stop_loss=800.0,
        take_profit=1700.0,
        broken_time=T0 + (offset_min + 1) * TICK if phase == RegionPhase.BROKEN else None,
        rearmed_once=False,
    )


#+------------------------------------------------------------------+
#| InMemoryStateStore — sanity                                      |
#+------------------------------------------------------------------+
def test_memory_store_session_round_trip():
    store = InMemoryStateStore()
    snap = SessionSnapshot(
        last_sl_time=T0 + 10 * TICK,
        trades_today=2,
        current_day=T0,
        current_entry_region=T0 + 5 * TICK,
        current_entry_position=12345,
    )
    store.save_session(snap)

    loaded = store.load_session()
    assert loaded is not None
    assert loaded.last_sl_time == snap.last_sl_time
    assert loaded.trades_today == 2
    assert loaded.current_entry_position == 12345


def test_memory_store_empty_returns_none():
    store = InMemoryStateStore()
    assert store.load_session() is None
    assert store.load_regions() == []


def test_memory_store_regions_round_trip():
    store = InMemoryStateStore()
    regions = [_mk_region(0), _mk_region(5), _mk_region(10)]
    store.save_regions(regions)

    loaded = store.load_regions()
    assert len(loaded) == 3
    assert loaded[0].location.bar_time == regions[0].location.bar_time
    assert loaded[0].stop_loss == 800.0


def test_memory_store_clear():
    store = InMemoryStateStore()
    store.save_session(SessionSnapshot(trades_today=1))
    store.save_regions([_mk_region(0)])
    store.clear()
    assert store.load_session() is None
    assert store.load_regions() == []


def test_memory_store_isolado_do_caller():
    """save_regions faz deep copy: mutar depois não afeta o store."""
    store = InMemoryStateStore()
    regions = [_mk_region(0)]
    store.save_regions(regions)
    regions[0].stop_loss = 9999.0  # muta o original

    loaded = store.load_regions()
    assert loaded[0].stop_loss == 800.0  # store preservou o valor original


#+------------------------------------------------------------------+
#| SqliteStateStore                                                |
#+------------------------------------------------------------------+
@pytest.fixture()
def sqlite_store(tmp_path):
    from engine.infrastructure.state.sqlite_store import SqliteStateStore
    db = tmp_path / "test.db"
    store = SqliteStateStore(db)
    yield store
    store.close()


def test_sqlite_store_session_round_trip(sqlite_store):
    snap = SessionSnapshot(
        last_sl_time=T0 + 10 * TICK,
        trades_today=3,
        current_day=T0,
        current_entry_region=T0 + 5 * TICK,
        current_entry_position=98765,
    )
    sqlite_store.save_session(snap)

    loaded = sqlite_store.load_session()
    assert loaded is not None
    assert loaded.trades_today == 3
    assert loaded.current_entry_position == 98765
    assert loaded.last_sl_time == snap.last_sl_time


def test_sqlite_store_regions_round_trip(sqlite_store):
    regions = [
        _mk_region(0, phase=RegionPhase.BROKEN),
        _mk_region(5, phase=RegionPhase.CONSUMED),
    ]
    sqlite_store.save_regions(regions)

    loaded = sqlite_store.load_regions()
    assert len(loaded) == 2
    assert loaded[0].location.bar_time == regions[0].location.bar_time
    assert loaded[0].phase == RegionPhase.BROKEN
    assert loaded[0].stop_loss == 800.0
    # segunda região está consumida
    assert loaded[1].phase == RegionPhase.CONSUMED


def test_sqlite_store_vazio_retorna_none(sqlite_store):
    assert sqlite_store.load_session() is None
    assert sqlite_store.load_regions() == []


def test_sqlite_store_persiste_entre_conexoes(tmp_path):
    """Simula 'reinício do processo': abre store, salva, fecha, abre de novo."""
    from engine.infrastructure.state.sqlite_store import SqliteStateStore
    db = tmp_path / "restart.db"

    # 1ª sessão: salva
    store1 = SqliteStateStore(db)
    store1.save_session(SessionSnapshot(trades_today=5, last_sl_time=T0))
    store1.save_regions([_mk_region(0)])
    store1.close()

    # 2ª sessão: abre e lê
    store2 = SqliteStateStore(db)
    loaded_snap = store2.load_session()
    loaded_regions = store2.load_regions()
    store2.close()

    assert loaded_snap is not None
    assert loaded_snap.trades_today == 5
    assert len(loaded_regions) == 1


def test_sqlite_store_clear(sqlite_store):
    sqlite_store.save_session(SessionSnapshot(trades_today=1))
    sqlite_store.save_regions([_mk_region(0)])
    sqlite_store.clear()
    assert sqlite_store.load_session() is None
    assert sqlite_store.load_regions() == []


def test_sqlite_store_save_regions_idempotente(sqlite_store):
    """Salvar 2x não duplica (DELETE + INSERT)."""
    regions = [_mk_region(0), _mk_region(5)]
    sqlite_store.save_regions(regions)
    sqlite_store.save_regions(regions)
    assert len(sqlite_store.load_regions()) == 2




#+------------------------------------------------------------------+
#| Integração: TradingSession + InMemoryStateStore                  |
#+------------------------------------------------------------------+
def test_session_save_and_load_round_trip():
    """Salva estado, cria nova sessão com o mesmo store, verifica persistência."""
    from datetime import datetime, time, timedelta
    from engine.application.trading_session import TradingSession
    from engine.config.presets import (
        DetectorParams, SessionParams, StdDevV510Preset, TimeWindowParams,
    )
    from engine.domain.shared.types import Bar, MarketSnapshot

    def _bar(now, high, low, vol):
        return Bar(time=now, open=(high + low) / 2, high=high, low=low,
                   close=(high + low) / 2, tick_volume=vol, real_volume=0.0)

    preset = StdDevV510Preset.model_validate({
        "name": "test", "strategy": "stddev_v510",
        "detector": DetectorParams(mute_open_min=0).model_dump(),
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=time(9, 0), end=time(17, 30)),
        ).model_dump(),
    })

    # 1. Sessão com store
    store = InMemoryStateStore()
    sess1 = TradingSession(preset, state_store=store)

    sess1.on_bar_closed(
        bar=_bar(T0 + 10 * TICK, 1200.0, 1000.0, 5000.0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    sess1.on_tick(MarketSnapshot(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    region_bar_time = sess1.regions.governing().bar_time
    sess1.notify_trade_opened(now=T0 + 12 * TICK,
                              region_bar_time=region_bar_time)
    sess1.notify_stop_loss(T0 + 15 * TICK)
    sess1.save_state()

    # 2. Nova sessão com mesmo store (simula reinício)
    sess2 = TradingSession(preset, state_store=store)

    assert sess2.trades_today == 1
    assert sess2.last_sl_time is not None
    assert sess2.current_entry_region == region_bar_time

    assert len(sess2.regions) == 1
    restored = sess2.regions.get(region_bar_time)
    assert restored is not None
    assert restored.phase.value == "BROKEN"
    assert restored.stop_loss == 800.0
    assert restored.take_profit == 1700.0


def test_session_sem_store_nao_quebra():
    """state_store=None: save/load são no-op."""
    from datetime import time
    from engine.application.trading_session import TradingSession
    from engine.config.presets import (
        DetectorParams, SessionParams, StdDevV510Preset, TimeWindowParams,
    )

    preset = StdDevV510Preset.model_validate({
        "name": "test", "strategy": "stddev_v510",
        "detector": DetectorParams(mute_open_min=0).model_dump(),
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=time(9, 0), end=time(17, 30)),
        ).model_dump(),
    })
    sess = TradingSession(preset)  # sem state_store
    sess.save_state()              # no-op
    assert sess.trades_today == 0



#+------------------------------------------------------------------+
#| F5e — Persistência de parciais/reforço                         |
#+------------------------------------------------------------------+
def test_session_snapshot_persiste_parciais_reforco():
    """Salva snapshot com todos os campos F5e e recarrega."""
    from datetime import datetime, timezone
    from engine.domain.state.store import SessionSnapshot
    from engine.infrastructure.state.memory_store import InMemoryStateStore

    store = InMemoryStateStore()
    snap = SessionSnapshot(
        last_sl_time=datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc),
        trades_today=2,
        current_day=datetime(2026, 10, 29, tzinfo=timezone.utc),
        current_entry_region=datetime(2026, 10, 29, 9, 10, tzinfo=timezone.utc),
        current_entry_position=12345,
        # F5e
        current_entry_price=1100.0,
        current_is_buy=True,
        reentry_armed=True,
        reentry_done=False,
        partials_filled=(0, 1),
    )
    store.save_session(snap)

    loaded = store.load_session()
    assert loaded is not None
    assert loaded.current_entry_price == 1100.0
    assert loaded.current_is_buy is True
    assert loaded.reentry_armed is True
    assert loaded.reentry_done is False
    assert loaded.partials_filled == (0, 1)


def test_trading_session_calendar_default_b3():
    """TradingSession sem calendar explícito → usa B3Calendar() por default."""
    from engine.application.trading_session import TradingSession
    from engine.domain.risk.exchange_calendar import B3Calendar
    from engine.config.presets import (
        DetectorParams, SessionParams, StdDevV510Preset, TimeWindowParams,
    )
    from datetime import time

    preset = StdDevV510Preset.model_validate({
        "name": "test", "strategy": "stddev_v510",
        "detector": DetectorParams(mute_open_min=0).model_dump(),
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=time(9, 0), end=time(17, 30)),
        ).model_dump(),
    })
    sess = TradingSession(preset)
    # O RegionManager deve ter o B3Calendar por default
    # (verificamos indiretamente pela validade por pregões)
    assert sess.regions._calendar is not None
    assert isinstance(sess.regions._calendar, B3Calendar)