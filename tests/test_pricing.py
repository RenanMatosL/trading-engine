"""Golden tests das funções puras de precificação (EA v4.60)."""
from __future__ import annotations

from datetime import datetime

from engine.domain.strategy.location import TradeLocation
from engine.domain.strategy.pricing import (
    EntryLevelMode,
    PricingConfig,
    SLLevelMode,
    entry_level,
    is_big_candle,
    stop_level,
    take_profit_level,
)

T0 = datetime(2026, 10, 29, 9, 0)


def _loc(high: float, low: float, big: bool = False) -> TradeLocation:
    return TradeLocation(
        bar_time=T0, high=high, low=low,
        volume=5000.0, big_candle=big,
    )


# ---- Candle grande ------------------------------------------------
def test_is_big_candle_por_range():
    cfg = PricingConfig(big_candle_min_range_points=400.0, point=1.0)
    assert is_big_candle(_loc(1400.0, 1000.0), cfg) is True
    assert is_big_candle(_loc(1399.0, 1000.0), cfg) is False


def test_is_big_candle_regra_desligada():
    cfg = PricingConfig(use_big_candle_rule=False)
    assert is_big_candle(_loc(1400.0, 1000.0), cfg) is False


# ---- ENTRY --------------------------------------------------------
def test_entry_default_candle_normal_e_mid():
    cfg = PricingConfig(
        entry_mode=EntryLevelMode.DEFAULT,
        big_candle_min_range_points=400.0,
        big_candle_entry_offset_points=200.0,
        point=1.0,
    )
    assert entry_level(_loc(1400.0, 1000.0), is_buy=True, cfg=cfg) == 1200.0
    assert entry_level(_loc(1400.0, 1000.0), is_buy=False, cfg=cfg) == 1200.0


def test_entry_default_candle_pequeno_e_mid():
    cfg = PricingConfig(
        entry_mode=EntryLevelMode.DEFAULT,
        big_candle_min_range_points=400.0,
        point=1.0,
    )
    assert entry_level(_loc(1300.0, 1000.0), is_buy=True, cfg=cfg) == 1150.0
    assert entry_level(_loc(1300.0, 1000.0), is_buy=False, cfg=cfg) == 1150.0


def test_entry_broken_extreme():
    cfg = PricingConfig(entry_mode=EntryLevelMode.BROKEN_EXTREME, point=1.0)
    assert entry_level(_loc(1400.0, 1000.0), is_buy=True,  cfg=cfg) == 1400.0
    assert entry_level(_loc(1400.0, 1000.0), is_buy=False, cfg=cfg) == 1000.0


def test_entry_broken_extreme_com_offset():
    cfg = PricingConfig(
        entry_mode=EntryLevelMode.BROKEN_EXTREME,
        entry_level_offset_points=50.0,
        point=1.0,
    )
    assert entry_level(_loc(1400.0, 1000.0), is_buy=True,  cfg=cfg) == 1450.0
    assert entry_level(_loc(1400.0, 1000.0), is_buy=False, cfg=cfg) == 950.0


def test_entry_mid_com_offset():
    cfg = PricingConfig(
        entry_mode=EntryLevelMode.MID,
        entry_level_offset_points=50.0,
        point=1.0,
    )
    assert entry_level(_loc(1400.0, 1000.0), is_buy=True,  cfg=cfg) == 1250.0
    assert entry_level(_loc(1400.0, 1000.0), is_buy=False, cfg=cfg) == 1150.0


def test_entry_opposite_extreme():
    cfg = PricingConfig(entry_mode=EntryLevelMode.OPPOSITE_EXTREME, point=1.0)
    assert entry_level(_loc(1400.0, 1000.0), is_buy=True,  cfg=cfg) == 1000.0
    assert entry_level(_loc(1400.0, 1000.0), is_buy=False, cfg=cfg) == 1400.0


def test_entry_immediate_retorna_zero():
    cfg = PricingConfig(entry_mode=EntryLevelMode.IMMEDIATE, point=1.0)
    assert entry_level(_loc(1400.0, 1000.0), is_buy=True,  cfg=cfg) == 0.0
    assert entry_level(_loc(1400.0, 1000.0), is_buy=False, cfg=cfg) == 0.0


# ---- STOP ---------------------------------------------------------
def test_stop_default_candle_normal():
    cfg = PricingConfig(
        sl_mode=SLLevelMode.DEFAULT,
        sl_points=200.0,
        big_candle_min_range_points=400.0,
        point=1.0,
    )
    assert stop_level(_loc(1300.0, 1000.0), is_buy=True,  cfg=cfg) == 800.0
    assert stop_level(_loc(1300.0, 1000.0), is_buy=False, cfg=cfg) == 1500.0


def test_stop_default_candle_grande():
    cfg = PricingConfig(
        sl_mode=SLLevelMode.DEFAULT,
        sl_points=200.0,
        big_candle_min_range_points=400.0,
        big_candle_sl_adjust_points=50.0,
        point=1.0,
    )
    assert stop_level(_loc(1400.0, 1000.0), is_buy=True,  cfg=cfg) == 950.0
    assert stop_level(_loc(1400.0, 1000.0), is_buy=False, cfg=cfg) == 1450.0


def test_stop_opposite_extreme():
    cfg = PricingConfig(
        sl_mode=SLLevelMode.OPPOSITE_EXTREME,
        sl_level_offset_points=100.0,
        point=1.0,
    )
    assert stop_level(_loc(1400.0, 1000.0), is_buy=True,  cfg=cfg) == 900.0
    assert stop_level(_loc(1400.0, 1000.0), is_buy=False, cfg=cfg) == 1500.0


def test_stop_mid():
    cfg = PricingConfig(
        sl_mode=SLLevelMode.MID,
        sl_level_offset_points=50.0,
        point=1.0,
    )
    assert stop_level(_loc(1400.0, 1000.0), is_buy=True,  cfg=cfg) == 1150.0
    assert stop_level(_loc(1400.0, 1000.0), is_buy=False, cfg=cfg) == 1250.0


# ---- TAKE PROFIT --------------------------------------------------
def test_take_profit_default():
    cfg = PricingConfig(use_final_tp=True, final_tp_points=600.0, point=1.0)
    assert take_profit_level(_loc(1400.0, 1000.0), is_buy=True,  cfg=cfg) == 1800.0
    assert take_profit_level(_loc(1400.0, 1000.0), is_buy=False, cfg=cfg) == 600.0


def test_take_profit_desligado():
    cfg = PricingConfig(use_final_tp=False)
    assert take_profit_level(_loc(1400.0, 1000.0), is_buy=True,  cfg=cfg) == 0.0
    assert take_profit_level(_loc(1400.0, 1000.0), is_buy=False, cfg=cfg) == 0.0


def test_take_profit_zero_points_desliga():
    cfg = PricingConfig(use_final_tp=True, final_tp_points=0.0)
    assert take_profit_level(_loc(1400.0, 1000.0), is_buy=True, cfg=cfg) == 0.0


# ---- Exemplo integrado do EA --------------------------------------
def test_risco_exemplo_ea_entrada_mid_sl_default():
    """Exemplo do EA: candle 171.000-171.400 (range 400), compra no mid
    171.200, SL=min-200=170.800 → risco 400 pts. (Candle grande na regra
    → risco é big_candle_entry_offset + big_candle_sl_adjust.)"""
    cfg = PricingConfig(
        entry_mode=EntryLevelMode.MID,
        sl_mode=SLLevelMode.DEFAULT,
        sl_points=200.0,
        big_candle_min_range_points=400.0,
        big_candle_entry_offset_points=200.0,
        big_candle_sl_adjust_points=0.0,
        point=1.0,
    )
    loc = _loc(171_400.0, 171_000.0)
    e = entry_level(loc, is_buy=True, cfg=cfg)
    s = stop_level(loc, is_buy=True, cfg=cfg)
    assert e == 171_200.0
    assert s == 171_000.0
    assert abs(e - s) == 200.0