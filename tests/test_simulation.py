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



#+------------------------------------------------------------------+
#| F5e — Slippage/spread                                          |
#+------------------------------------------------------------------+
def test_slippage_afeta_fill_de_mercado():
    """Compra a mercado com slippage=2 preenche em entry+2."""
    from engine.application.simulation import SimulatedExecutor
    from engine.application.trading_session import TradingSession
    from engine.application.intent import TradeIntent
    from engine.domain.strategy.location import RegionState, TradeLocation

    preset = _preset()
    executor = SimulatedExecutor(preset, slippage_points=2.0)

    loc = TradeLocation(
        bar_time=T0, high=1200.0, low=1000.0, volume=5000.0, big_candle=False,
    )
    region = RegionState(location=loc)
    region.phase = region.phase.BROKEN
    region.is_buy = True
    region.stop_loss = 800.0
    region.take_profit = 1700.0

    intent = TradeIntent(
        region=region, is_buy=True, entry_price=1100.0,
        stop_loss=800.0, take_profit=1700.0, volume=6.0,
        as_pending=False, reason="test", created_at=T0,
    )

    # Simula um tick com preço favorável
    snapshot = MarketSnapshot(ask=1100.0, bid=1099.0, now=T0 + TICK)
    executor.execute(intent, snapshot)

    # O fill deve ser entry + slippage = 1102
    assert executor.open_trade is not None
    assert executor.open_trade.entry_price == 1102.0


def test_slippage_afeta_fill_de_limite():
    """Compra limite com slippage=2 preenche em entry+2 (pior caso)."""
    from engine.application.simulation import SimulatedExecutor
    from engine.application.intent import TradeIntent
    from engine.domain.strategy.location import RegionState, TradeLocation

    preset = _preset()
    executor = SimulatedExecutor(preset, slippage_points=2.0)

    loc = TradeLocation(
        bar_time=T0, high=1200.0, low=1000.0, volume=5000.0, big_candle=False,
    )
    region = RegionState(location=loc)
    region.phase = region.phase.BROKEN
    region.is_buy = True
    region.stop_loss = 800.0
    region.take_profit = 1700.0

    intent = TradeIntent(
        region=region, is_buy=True, entry_price=1100.0,
        stop_loss=800.0, take_profit=1700.0, volume=6.0,
        as_pending=True, reason="test", created_at=T0,
    )

    # 1. Executa (arma limite)
    snapshot1 = MarketSnapshot(ask=1105.0, bid=1104.0, now=T0 + TICK)
    executor.execute(intent, snapshot1)
    assert executor.pending_limit is not None

    # 2. Preço volta ao entry → fill com slippage
    snapshot2 = MarketSnapshot(ask=1100.0, bid=1099.0, now=T0 + 2 * TICK)
    executor.on_tick(snapshot2)
    assert executor.open_trade is not None
    assert executor.open_trade.entry_price == 1102.0  # entry + slippage


def test_slippage_zero_nao_altera_fill():
    """slippage=0 (default) → fill em entry_price (comportamento antigo)."""
    from engine.application.simulation import SimulatedExecutor
    from engine.application.intent import TradeIntent
    from engine.domain.strategy.location import RegionState, TradeLocation

    preset = _preset()
    executor = SimulatedExecutor(preset)  # slippage=0 default

    loc = TradeLocation(
        bar_time=T0, high=1200.0, low=1000.0, volume=5000.0, big_candle=False,
    )
    region = RegionState(location=loc)
    region.phase = region.phase.BROKEN
    region.is_buy = True
    region.stop_loss = 800.0
    region.take_profit = 1700.0

    intent = TradeIntent(
        region=region, is_buy=True, entry_price=1100.0,
        stop_loss=800.0, take_profit=1700.0, volume=6.0,
        as_pending=False, reason="test", created_at=T0,
    )

    snapshot = MarketSnapshot(ask=1100.0, bid=1099.0, now=T0 + TICK)
    executor.execute(intent, snapshot)

    assert executor.open_trade is not None
    assert executor.open_trade.entry_price == 1100.0  # sem slippage

#+------------------------------------------------------------------+
#| F8 — Parciais e Reforço no simulador                             |
#+------------------------------------------------------------------+
from datetime import datetime, timezone
from engine.application.intent import TradeIntent
from engine.application.simulation import SimulatedExecutor, ExitReason
from engine.domain.shared.types import MarketSnapshot
from engine.domain.strategy.location import RegionState, RegionPhase, TradeLocation

def test_sim_partial_exit_fill():
    """F8: Simula um trade atingindo o alvo do Tier 1 e verifica a parcial."""
    preset = _preset()

    # 1. Configura o preset para forçar parciais
    # (como os campos são "frozen", precisamos recriar o RiskParams, mas
    #  para simplificar, vamos usar model_copy e setar via dict)
    from engine.config.presets import PartialExitType, PartialTier
    risk = preset.risk.model_copy(update={
        "use_partial_exit": True,
        "partial_points": 100.0,
        "partial_tiers": [
            PartialTier(contracts=2, points=0),
            PartialTier(contracts=0, points=0),
            PartialTier(contracts=0, points=0),
        ],
        "exit_type": PartialExitType.POINTS,
        "breakeven_after_partial": True,  # ← ADICIONADO
    })
    preset = preset.model_copy(update={"risk": risk})

    executor = SimulatedExecutor(preset, initial_balance=100_000.0)

    # 2. Cria um TradeIntent fictício
    region = RegionState(
        location=TradeLocation(
            bar_time=datetime.now(timezone.utc),
            high=1000.0, low=900.0,
            volume=1000.0, big_candle=False,
        ),
    )
    region.phase = RegionPhase.BROKEN
    region.is_buy = True
    intent = TradeIntent(
        region=region,
        is_buy=True,
        entry_price=950.0,
        stop_loss=900.0,
        take_profit=1200.0,
        volume=6.0,
        as_pending=False,
        reason="test",
        created_at=datetime.now(timezone.utc),
    )

    # 3. Tick inicial: preço no entry (abre o trade)
    snap_open = MarketSnapshot(
        ask=950.0, bid=950.0, now=datetime.now(timezone.utc), spread=0.0,
    )
    executor.execute(intent, snap_open)
    assert executor.open_trade is not None
    assert executor.open_trade.remaining_volume == 6.0

    # 4. Tick atingindo Tier 1 (bid = 1050 = entry + 100)
    snap_tier1 = MarketSnapshot(
        ask=1050.0, bid=1050.0, now=datetime.now(timezone.utc), spread=0.0,
    )
    executor.on_tick(snap_tier1)

    # 5. Verificações do Tier 1
    assert len(executor.open_trade.fills) == 1
    assert executor.open_trade.fills[0].reason == ExitReason.PARTIAL
    assert executor.open_trade.fills[0].price == 1050.0
    assert executor.open_trade.remaining_volume == 4.0  # 6 - 2
    assert executor.open_trade.stop_loss == 950.0  # Breakeven (se breakeven_after_partial=True)


def test_sim_reentry_fill():
    """F8: Simula o preço avançando, voltando e disparando o reforço."""
    preset = _preset()

    risk = preset.risk.model_copy(update={
        "use_reentry": True,
        "reentry_arm_points": 50.0,
        "reentry_contracts": 3,
        "use_partial_exit": False,
        "total_contracts": 2,  # <-- garante que o trade abra com 2 contratos
    })
    preset = preset.model_copy(update={"risk": risk})

    executor = SimulatedExecutor(preset, initial_balance=100_000.0)

    # 2. Cria o TradeIntent (sem TP/SL para não fechar acidentalmente)
    region = RegionState(
        location=TradeLocation(
            bar_time=datetime.now(timezone.utc),
            high=1000.0, low=900.0,
            volume=1000.0, big_candle=False,
        ),
    )
    region.phase = RegionPhase.BROKEN
    region.is_buy = True
    intent = TradeIntent(
        region=region,
        is_buy=True,
        entry_price=950.0,
        stop_loss=800.0,  # SL bem longe
        take_profit=1500.0,  # TP bem longe
        volume=2.0,
        as_pending=False,
        reason="test",
        created_at=datetime.now(timezone.utc),
    )

    # 3. Abre o trade
    snap_open = MarketSnapshot(
        ask=950.0, bid=950.0, now=datetime.now(timezone.utc), spread=0.0,
    )
    executor.execute(intent, snap_open)
    assert executor.open_trade.remaining_volume == 2.0  # volume inicial (só o trade original)

    # 4. Preço avança 60 pontos (arma o reforço)
    snap_advance = MarketSnapshot(
        ask=1010.0, bid=1010.0, now=datetime.now(timezone.utc), spread=0.0,
    )
    executor.on_tick(snap_advance)
    assert executor.open_trade.reentry_armed is True
    assert executor.open_trade.reentry_done is False

    # 5. Preço volta ao entry (950) — dispara o reforço
    snap_return = MarketSnapshot(
        ask=949.0, bid=950.0, now=datetime.now(timezone.utc), spread=0.0,
    )
    executor.on_tick(snap_return)

    # 6. Verificações do reforço
    assert executor.open_trade.reentry_done is True
    assert executor.open_trade.remaining_volume == 5.0  # 2 originais + 3 reforço