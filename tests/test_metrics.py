"""Golden tests das métricas de backtest (F6)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engine.application.metrics import (
    average_win_loss,
    max_drawdown,
    profit_factor,
    sharpe,
    total_return,
    win_rate,
)
from engine.application.simulation import SimulatedTrade, ExitReason, SimulatedFill


T0 = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)


def _trade(
    *,
    pnl_money: float,
    pnl_points: float | None = None,
    entry_price: float = 1000.0,
    is_buy: bool = True,
    exit_reason: ExitReason = ExitReason.TAKE_PROFIT,
) -> SimulatedTrade:
    """Cria um SimulatedTrade mínimo para os testes."""
    return SimulatedTrade(
        region_bar_time=T0,
        is_buy=is_buy,
        entry_time=T0,
        entry_price=entry_price,
        stop_loss=900.0 if is_buy else 1100.0,
        take_profit=1100.0 if is_buy else 900.0,
        initial_volume=1.0,
        fills=[],
        pnl_points=pnl_points if pnl_points is not None else pnl_money,
        pnl_money=pnl_money,
        exit_reason=exit_reason,
    )


#+------------------------------------------------------------------+
#| Sharpe                                                           |
#+------------------------------------------------------------------+
def test_sharpe_sem_trades_zero():
    assert sharpe([]) == 0.0


def test_sharpe_um_trade_zero():
    """1 trade só: stdev precisa de >= 2 amostras."""
    assert sharpe([_trade(pnl_money=100.0)]) == 0.0


def test_sharpe_todos_iguais_zero():
    """Todos os P&L iguais → std=0 → Sharpe=0."""
    trades = [_trade(pnl_money=100.0) for _ in range(5)]
    assert sharpe(trades) == 0.0


def test_sharpe_positivo():
    """P&L positivos variados → Sharpe > 0."""
    trades = [
        _trade(pnl_money=100.0),
        _trade(pnl_money=200.0),
        _trade(pnl_money=150.0),
    ]
    assert sharpe(trades) > 0


#+------------------------------------------------------------------+
#| Max drawdown                                                     |
#+------------------------------------------------------------------+
def test_max_drawdown_curva_vazia_zero():
    assert max_drawdown([]) == 0.0


def test_max_drawdown_um_ponto_zero():
    assert max_drawdown([(T0, 100_000.0)]) == 0.0


def test_max_drawdown_sem_queda_zero():
    """Equity sempre subindo → drawdown = 0."""
    curve = [
        (T0, 100_000.0),
        (T0, 110_000.0),
        (T0, 120_000.0),
    ]
    assert max_drawdown(curve) == 0.0


def test_max_drawdown_50_por_cento():
    """Equity cai de 100k para 50k → drawdown = 0.5."""
    curve = [
        (T0, 100_000.0),
        (T0, 150_000.0),
        (T0, 75_000.0),  # 50% do pico (150k)
    ]
    assert max_drawdown(curve) == pytest.approx(0.5)


#+------------------------------------------------------------------+
#| Win rate                                                         |
#+------------------------------------------------------------------+
def test_win_rate_sem_trades_zero():
    assert win_rate([]) == 0.0


def test_win_rate_60_por_cento():
    trades = [
        _trade(pnl_money=100.0),
        _trade(pnl_money=200.0),
        _trade(pnl_money=50.0),
        _trade(pnl_money=-100.0),
        _trade(pnl_money=-50.0),
    ]
    assert win_rate(trades) == pytest.approx(3 / 5)


#+------------------------------------------------------------------+
#| Profit factor                                                    |
#+------------------------------------------------------------------+
def test_profit_factor_sem_trades_zero():
    assert profit_factor([]) == 0.0


def test_profit_factor_2():
    """Ganhos: 100+200=300. Perdas: |-100|=100. PF = 3.0."""
    trades = [
        _trade(pnl_money=100.0),
        _trade(pnl_money=200.0),
        _trade(pnl_money=-100.0),
    ]
    assert profit_factor(trades) == pytest.approx(3.0)


def test_profit_factor_infinito():
    """Sem perdas → PF = inf."""
    trades = [_trade(pnl_money=100.0), _trade(pnl_money=200.0)]
    assert profit_factor(trades) == pytest.approx(float("inf"))


#+------------------------------------------------------------------+
#| Average win / average loss                                       |
#+------------------------------------------------------------------+
def test_average_win_loss_sem_trades_zero():
    aw, al = average_win_loss([])
    assert aw == 0.0
    assert al == 0.0


def test_average_win_loss_valores():
    """Wins: 100, 300 → média 200. Losses: -100, -200 → média 150."""
    trades = [
        _trade(pnl_money=100.0),
        _trade(pnl_money=300.0),
        _trade(pnl_money=-100.0),
        _trade(pnl_money=-200.0),
    ]
    aw, al = average_win_loss(trades)
    assert aw == pytest.approx(200.0)
    assert al == pytest.approx(150.0)


#+------------------------------------------------------------------+
#| Total return                                                     |
#+------------------------------------------------------------------+
def test_total_return_sem_trades_zero():
    assert total_return([], 100_000.0) == 0.0


def test_total_return_10_por_cento():
    """3 trades: +1000 +2000 -500 = +2500. Sobre 100k → +2.5%."""
    trades = [
        _trade(pnl_money=1000.0),
        _trade(pnl_money=2000.0),
        _trade(pnl_money=-500.0),
    ]
    assert total_return(trades, 100_000.0) == pytest.approx(2.5)


def test_total_return_initial_balance_zero_zero():
    """Proteção contra divisão por zero."""
    assert total_return([_trade(pnl_money=100.0)], 0.0) == 0.0