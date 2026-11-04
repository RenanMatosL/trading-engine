"""Métricas de performance para backtest (F6).

Funções puras: recebem `SimulatedTrade` (F2d) e/ou `equity_curve`, retornam
float. Zero dependências externas (só stdlib `math` / `statistics`).

Uso:
    from engine.application.metrics import sharpe, max_drawdown, ...
    sharpe_ratio = sharpe(result.trades, result.equity_curve)
    dd = max_drawdown(result.equity_curve)
    wr = win_rate(result.trades)
    pf = profit_factor(result.trades)
    awl = average_win_loss(result.trades)
    tr = total_return(result.trades, result.stats["n_trades"])
"""
from __future__ import annotations

import math
import statistics

from engine.application.simulation import SimulatedTrade


#+------------------------------------------------------------------+
#| Helpers internos                                                 |
#+------------------------------------------------------------------+
def _pnl_money(trades: list[SimulatedTrade]) -> list[float]:
    """P&L monetário de cada trade fechado."""
    return [t.pnl_money for t in trades if t.is_closed]


def _equity_values(equity_curve: list[tuple]) -> list[float]:
    """Só os valores de equity (sem timestamps)."""
    return [balance for _, balance in equity_curve]


#+------------------------------------------------------------------+
#| Sharpe ratio                                                     |
#+------------------------------------------------------------------+
def sharpe(
    trades: list[SimulatedTrade],
    *,
    periods_per_year: int = 252,
) -> float:
    """Sharpe ratio (anualizado).

    Usa o retorno por trade (não por barra). `periods_per_year=252` assume
    ~1 trade/dia útil. Se você fizer N trades/dia, ajuste (ex: 252*N).

    Retorna `0.0` se:
      - Não há trades.
      - Desvio-padrão dos retornos é 0 (todos os trades com mesmo P&L).
    """
    pnls = _pnl_money(trades)
    if len(pnls) < 2:
        return 0.0
    mean = statistics.mean(pnls)
    try:
        std = statistics.stdev(pnls)  # amostral (n-1)
    except statistics.StatisticsError:
        return 0.0
    if std == 0.0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


#+------------------------------------------------------------------+
#| Max drawdown                                                     |
#+------------------------------------------------------------------+
def max_drawdown(equity_curve: list[tuple]) -> float:
    """Max drawdown em % (0.0 = sem drawdown, 1.0 = perdeu 100%).

    Percorre a equity curve, rastreia o pico e calcula a maior queda
    percentual do pico.
    """
    values = _equity_values(equity_curve)
    if len(values) < 2:
        return 0.0

    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


#+------------------------------------------------------------------+
#| Win rate                                                         |
#+------------------------------------------------------------------+
def win_rate(trades: list[SimulatedTrade]) -> float:
    """Fração de trades com lucro (> 0). 0.0 a 1.0."""
    pnls = _pnl_money(trades)
    if not pnls:
        return 0.0
    winners = sum(1 for p in pnls if p > 0)
    return winners / len(pnls)


#+------------------------------------------------------------------+
#| Profit factor                                                    |
#+------------------------------------------------------------------+
def profit_factor(trades: list[SimulatedTrade]) -> float:
    """Lucro bruto / |prejuízo bruto|.

    - > 1.0 = lucrativo.
    - < 1.0 = prejuízo.
    - Inf se não há prejuízo (retorna `math.inf`).
    - 0.0 se não há trades.
    """
    pnls = _pnl_money(trades)
    if not pnls:
        return 0.0
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        return math.inf if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


#+------------------------------------------------------------------+
#| Average win / average loss                                       |
#+------------------------------------------------------------------+
def average_win_loss(trades: list[SimulatedTrade]) -> tuple[float, float]:
    """Retorna (média dos wins, média dos losses em valor absoluto)."""
    pnls = _pnl_money(trades)
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0
    return avg_win, avg_loss


#+------------------------------------------------------------------+
#| Total return                                                     |
#+------------------------------------------------------------------+
def total_return(
    trades: list[SimulatedTrade],
    initial_balance: float,
) -> float:
    """Retorno total em % (ex: 5.0 = +5%).

    `initial_balance` deve ser o saldo inicial do backtest.
    """
    if initial_balance <= 0:
        return 0.0
    total_pnl = sum(_pnl_money(trades))
    return (total_pnl / initial_balance) * 100.0