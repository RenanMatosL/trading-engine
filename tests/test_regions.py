"""Golden tests do RegionManager (domínio puro).

Não testa: filtros de sessão, cooldown, limite diário, ordens.
Testa: criação, rompimento, governança, expiração, rearme, substituição.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from engine.domain.shared.types import MarketSnapshot
from engine.domain.strategy.location import RegionPhase, RegisterResult
from engine.domain.strategy.regions import RegionManager

T0 = datetime(2026, 10, 29, 9, 0)
TICK = timedelta(minutes=1)

# Stop/TP triviais para os testes — a matemática real fica no preset.
STOP = lambda loc, is_buy: loc.low - 200.0 if is_buy else loc.high + 200.0  # noqa: E731
TP = lambda loc, is_buy: loc.mid + 600.0 if is_buy else loc.mid - 600.0    # noqa: E731


def _snap(ask: float, bid: float, now: datetime) -> MarketSnapshot:
    return MarketSnapshot(ask=ask, bid=bid, now=now)


#+------------------------------------------------------------------+
def test_register_cria_regiao():
    mgr = RegionManager()
    res, st = mgr.register(
        bar_time=T0, high=1000.0, low=900.0,
        volume=5000.0, big_candle=False, now=T0,
    )
    assert res == RegisterResult.CREATED
    assert st is not None
    assert st.phase == RegionPhase.WAITING_BREAKOUT
    assert st.volume == 5000.0
    assert len(mgr) == 1


def test_register_duplicada_e_ignorada():
    mgr = RegionManager()
    mgr.register(bar_time=T0, high=1000.0, low=900.0,
                 volume=5000.0, big_candle=False, now=T0)
    res, st = mgr.register(bar_time=T0, high=1000.0, low=900.0,
                           volume=5000.0, big_candle=False, now=T0)
    assert res == RegisterResult.SKIPPED_DUPLICATE
    assert st is None
    assert len(mgr) == 1


def test_register_fila_cheia_substitui_menor_volume():
    mgr = RegionManager(max_loc=3)
    for i in range(3):
        mgr.register(bar_time=T0 + i * TICK, high=1000.0, low=900.0,
                     volume=1000.0 * (i + 1), big_candle=False, now=T0)
    # Fila cheia (3). Nova região de volume maior deve substituir a menor.
    res, st = mgr.register(bar_time=T0 + 3 * TICK, high=1000.0, low=900.0,
                           volume=5000.0, big_candle=False, now=T0)
    assert res == RegisterResult.REPLACED_LOWEST
    assert st is not None
    assert len(mgr) == 3
    assert all(s.volume >= 2000.0 for s in mgr.all())


def test_register_fila_cheia_volume_baixo_e_ignorado():
    mgr = RegionManager(max_loc=2)
    mgr.register(bar_time=T0, high=1000.0, low=900.0,
                 volume=5000.0, big_candle=False, now=T0)
    mgr.register(bar_time=T0 + TICK, high=1000.0, low=900.0,
                 volume=6000.0, big_candle=False, now=T0)
    res, st = mgr.register(bar_time=T0 + 2 * TICK, high=1000.0, low=900.0,
                           volume=1000.0, big_candle=False, now=T0)
    assert res == RegisterResult.SKIPPED_FULL_QUEUE
    assert st is None


def test_rompimento_maxima_vira_compra():
    mgr = RegionManager()
    _, st = mgr.register(bar_time=T0, high=1000.0, low=900.0,
                         volume=5000.0, big_candle=False, now=T0)
    assert st is not None and st.phase == RegionPhase.WAITING_BREAKOUT
    # ask acima do high rompe para cima
    broke = mgr.update_breakouts(_snap(ask=1001.0, bid=999.0, now=T0 + TICK),
                                  stop_level_fn=STOP, take_profit_fn=TP)
    assert len(broke) == 1
    assert broke[0].is_buy is True
    assert broke[0].phase == RegionPhase.BROKEN
    assert broke[0].stop_loss == 700.0   # low - 200
    assert broke[0].take_profit == 1550.0  # mid + 600


def test_rompimento_minima_vira_venda():
    mgr = RegionManager()
    mgr.register(bar_time=T0, high=1000.0, low=900.0,
                 volume=5000.0, big_candle=False, now=T0)
    broke = mgr.update_breakouts(_snap(ask=901.0, bid=899.0, now=T0 + TICK),
                                  stop_level_fn=STOP, take_profit_fn=TP)
    assert len(broke) == 1
    assert broke[0].is_buy is False
    assert broke[0].stop_loss == 1200.0   # high + 200
    assert broke[0].take_profit == 350.0  # mid - 600


def test_governing_maior_volume():
    mgr = RegionManager()
    mgr.register(bar_time=T0, high=1000.0, low=900.0, volume=3000.0,
                 big_candle=False, now=T0)
    mgr.register(bar_time=T0 + TICK, high=1000.0, low=900.0, volume=7000.0,
                 big_candle=False, now=T0)
    # Rompe as duas
    mgr.update_breakouts(_snap(ask=1001.0, bid=1001.0, now=T0 + 2 * TICK),
                          stop_level_fn=STOP, take_profit_fn=TP)
    gov = mgr.governing()
    assert gov is not None
    assert gov.volume == 7000.0


def test_governing_so_considera_broken():
    mgr = RegionManager()
    mgr.register(bar_time=T0, high=1000.0, low=900.0, volume=7000.0,
                 big_candle=False, now=T0)
    # Não rompeu ainda → não é candidata
    assert mgr.governing() is None


def test_ttl_pos_rompimento_expira():
    mgr = RegionManager(breakout_ttl_min=10)
    mgr.register(bar_time=T0, high=1000.0, low=900.0, volume=5000.0,
                 big_candle=False, now=T0)
    mgr.update_breakouts(_snap(ask=1001.0, bid=1001.0, now=T0 + TICK),
                          stop_level_fn=STOP, take_profit_fn=TP)
    # Antes do TTL: não expira
    assert mgr.sweep_expired(T0 + TICK + timedelta(minutes=9)) == []
    # Depois do TTL: expira
    expired = mgr.sweep_expired(T0 + TICK + timedelta(minutes=11))
    assert len(expired) == 1
    assert expired[0].phase == RegionPhase.CONSUMED


def test_validade_por_dias_expira():
    mgr = RegionManager(valid_days=2)
    mgr.register(bar_time=T0, high=1000.0, low=900.0, volume=5000.0,
                 big_candle=False, now=T0)
    # 2 dias depois: ainda válida
    assert mgr.sweep_expired(T0 + timedelta(days=2)) == []
    # 3 dias depois: expira
    expired = mgr.sweep_expired(T0 + timedelta(days=3))
    assert len(expired) == 1
    assert expired[0].phase == RegionPhase.CONSUMED


def test_consume_marca_consumed():
    mgr = RegionManager()
    mgr.register(bar_time=T0, high=1000.0, low=900.0, volume=5000.0,
                 big_candle=False, now=T0)
    st = mgr.consume(T0)
    assert st is not None
    assert st.phase == RegionPhase.CONSUMED


def test_rearm_apos_sl_uma_vez():
    mgr = RegionManager()
    mgr.register(bar_time=T0, high=1000.0, low=900.0, volume=5000.0,
                 big_candle=False, now=T0)
    mgr.update_breakouts(_snap(ask=1001.0, bid=1001.0, now=T0 + TICK),
                          stop_level_fn=STOP, take_profit_fn=TP)
    # 1º rearme (InpAllowReverse: 1x)
    st = mgr.rearm_after_sl(T0, allow_unlimited=False)
    assert st is not None
    assert st.phase == RegionPhase.REARMED
    assert st.rearmed_once is True
    # Reabre (rompe de novo) para poder rearmar 2ª vez
    mgr.update_breakouts(_snap(ask=1001.0, bid=1001.0, now=T0 + 2 * TICK),
                          stop_level_fn=STOP, take_profit_fn=TP)
    # 2º rearme: não pode (limite atingido) → CONSUMED
    st = mgr.rearm_after_sl(T0, allow_unlimited=False)
    assert st is not None
    assert st.phase == RegionPhase.CONSUMED


def test_rearm_apos_sl_sem_limite():
    mgr = RegionManager()
    mgr.register(bar_time=T0, high=1000.0, low=900.0, volume=5000.0,
                 big_candle=False, now=T0)
    mgr.update_breakouts(_snap(ask=1001.0, bid=1001.0, now=T0 + TICK),
                          stop_level_fn=STOP, take_profit_fn=TP)
    for i in range(5):
        st = mgr.rearm_after_sl(T0, allow_unlimited=True)
        assert st is not None
        assert st.phase == RegionPhase.REARMED
        mgr.update_breakouts(_snap(ask=1001.0, bid=1001.0,
                                    now=T0 + (i + 2) * TICK),
                              stop_level_fn=STOP, take_profit_fn=TP)