"""Funções puras de precificação (entry / stop / take-profit).

Espelha `EntryLevelFor()`, `StopLevelFor()` e o cálculo de TP do EA v4.60.
Zero dependência de MT5 ou de ordens: entrada = TradeLocation + is_buy +
PricingConfig; saída = preço float. Testável isoladamente.

Convenções:
  - `is_buy=True`  → operação de compra  (SL abaixo, TP acima)
  - `is_buy=False` → operação de venda   (SL acima, TP abaixo)
  - `location.mid` = (high + low) / 2
  - Os offsets são em PONTOS (como no EA). Quem converte para preço é
    o caller, usando `_point` do símbolo (WIN$N: 1.0, forex: 0.00001 etc).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.domain.strategy.location import TradeLocation


class EntryLevelMode(str, Enum):
    """Onde entrar no pullback após rompimento (espelha ENUM_ENTRY_LEVEL)."""
    DEFAULT = "default"                    # regra vigente (mid; candle grande: extremo -/+ offset)
    BROKEN_EXTREME = "broken_extreme"      # compra: high | venda: low
    MID = "mid"                            # (high + low) / 2
    OPPOSITE_EXTREME = "opposite_extreme"  # compra: low | venda: high
    IMMEDIATE = "immediate"                # entra a mercado no rompimento


class SLLevelMode(str, Enum):
    """Onde fica o stop loss (espelha ENUM_SL_LEVEL)."""
    DEFAULT = "default"                    # extremo oposto -/+ sl_points (grande: extremo ± adjust)
    OPPOSITE_EXTREME = "opposite_extreme"  # extremo oposto -/+ sl_level_offset
    MID = "mid"                            # mid -/+ sl_level_offset


@dataclass(frozen=True, slots=True)
class PricingConfig:
    """Subconjunto do preset que importa para precificação.

    O TradingSession (F2c) traduz preset.entry/sl/tp/big_candle → isto.
    Mantém o domínio de pricing ortogonal ao formato YAML.
    """
    # ---- Entrada ----
    entry_mode: EntryLevelMode = EntryLevelMode.DEFAULT
    entry_level_offset_points: float = 0.0

    # ---- Stop ----
    sl_mode: SLLevelMode = SLLevelMode.DEFAULT
    sl_points: float = 200.0            # usado em SL_DEFAULT (fora do candle grande)
    sl_level_offset_points: float = 0.0 # usado em SL_OPPOSITE_EXTREME / SL_MID

    # ---- Take Profit ----
    use_final_tp: bool = True
    final_tp_points: float = 600.0

    # ---- Candle grande ----
    use_big_candle_rule: bool = True
    big_candle_min_range_points: float = 400.0
    big_candle_entry_offset_points: float = 200.0
    big_candle_sl_adjust_points: float = 0.0

    # ---- Escala de preço (1 ponto = _point em preço) ----
    point: float = 1.0


#+------------------------------------------------------------------+
#| Helpers internos                                                 |
#+------------------------------------------------------------------+
def _mid(loc: TradeLocation) -> float:
    return (loc.high + loc.low) / 2.0


def is_big_candle(loc: TradeLocation, cfg: PricingConfig) -> bool:
    """Regra do EA: range >= min_range E regra ligada."""
    if not cfg.use_big_candle_rule:
        return False
    range_points = (loc.high - loc.low) / cfg.point
    return range_points >= cfg.big_candle_min_range_points


#+------------------------------------------------------------------+
#| ENTRY                                                            |
#+------------------------------------------------------------------+
def entry_level(loc: TradeLocation, is_buy: bool, cfg: PricingConfig) -> float:
    """Nível de entrada conforme o modo escolhido.

    - DEFAULT:          mid (normal) / extremo -/+ offset (candle grande)
    - BROKEN_EXTREME:   compra no high | venda no low, +entry_offset na
                        direção do rompimento
    - MID:              mid, ±entry_offset na direção do rompimento
    - OPPOSITE_EXTREME: compra no low | venda no high, ±entry_offset
    - IMMEDIATE:        retorna 0.0 (sinaliza "sem nível"; entra a mercado)
    """
    if cfg.entry_mode == EntryLevelMode.IMMEDIATE:
        return 0.0

    off = cfg.entry_level_offset_points * cfg.point
    mid = _mid(loc)

    if cfg.entry_mode == EntryLevelMode.DEFAULT:
        if is_big_candle(loc, cfg):
            big_off = cfg.big_candle_entry_offset_points * cfg.point
            return (loc.low + big_off) if is_buy else (loc.high - big_off)
        return mid

    if cfg.entry_mode == EntryLevelMode.BROKEN_EXTREME:
        base = loc.high if is_buy else loc.low
    elif cfg.entry_mode == EntryLevelMode.MID:
        base = mid
    else:  # OPPOSITE_EXTREME
        base = loc.low if is_buy else loc.high

    # Ajuste na direção do rompimento (positivo = a favor do rompimento)
    return base + (off if is_buy else -off)


#+------------------------------------------------------------------+
#| STOP LOSS                                                        |
#+------------------------------------------------------------------+
def stop_level(loc: TradeLocation, is_buy: bool, cfg: PricingConfig) -> float:
    """Nível do stop loss conforme o modo escolhido.

    - DEFAULT:          extremo oposto -/+ sl_points (normal)
                        extremo oposto -/+ big_candle_sl_adjust (candle grande)
    - OPPOSITE_EXTREME: extremo oposto -/+ sl_level_offset_points
    - MID:              mid -/+ sl_level_offset_points

    A convenção de sinal garante que o SL fica sempre do lado correto:
    compra → abaixo do preço; venda → acima do preço.
    """
    off = cfg.sl_level_offset_points * cfg.point
    mid = _mid(loc)

    if cfg.sl_mode == SLLevelMode.OPPOSITE_EXTREME:
        return (loc.low - off) if is_buy else (loc.high + off)

    if cfg.sl_mode == SLLevelMode.MID:
        return (mid - off) if is_buy else (mid + off)

    # DEFAULT
    if is_big_candle(loc, cfg):
        big_adj = cfg.big_candle_sl_adjust_points * cfg.point
        return (loc.low - big_adj) if is_buy else (loc.high + big_adj)

    sl_pts = cfg.sl_points * cfg.point
    return (loc.low - sl_pts) if is_buy else (loc.high + sl_pts)


#+------------------------------------------------------------------+
#| TAKE PROFIT                                                      |
#+------------------------------------------------------------------+
def take_profit_level(loc: TradeLocation, is_buy: bool, cfg: PricingConfig) -> float:
    """TP a partir do MID, ±final_tp_points. Retorna 0.0 se desligado."""
    if not cfg.use_final_tp or cfg.final_tp_points <= 0.0:
        return 0.0
    tp_pts = cfg.final_tp_points * cfg.point
    mid = _mid(loc)
    return (mid + tp_pts) if is_buy else (mid - tp_pts)