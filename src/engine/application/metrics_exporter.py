"""Exportador de métricas (F12) — formato Prometheus.

Contadores globais (thread-safe para o loop síncrono do motor).
"""
from __future__ import annotations

from typing import Dict

# Contadores globais
_trades_opened: int = 0
_trades_closed: int = 0
_trades_won: int = 0
_trades_lost: int = 0
_pnl_total: float = 0.0
_pnl_by_symbol: Dict[str, float] = {}
_trades_by_symbol: Dict[str, int] = {}
_last_update: float = 0.0

def record_trade_opened(symbol: str) -> None:
    """Registra a abertura de um trade."""
    global _trades_opened
    _trades_opened += 1
    _trades_by_symbol[symbol] = _trades_by_symbol.get(symbol, 0) + 1

def record_trade_closed(symbol: str, pnl_money: float) -> None:
    """Registra o fechamento de um trade."""
    global _trades_closed, _trades_won, _trades_lost, _pnl_total
    _trades_closed += 1
    _pnl_total += pnl_money
    _pnl_by_symbol[symbol] = _pnl_by_symbol.get(symbol, 0.0) + pnl_money
    if pnl_money > 0:
        _trades_won += 1
    elif pnl_money < 0:
        _trades_lost += 1

def get_metrics() -> str:
    """Retorna as métricas no formato Prometheus (text/plain)."""
    lines = [
        "# HELP engine_trades_opened_total Total de trades abertos.",
        "# TYPE engine_trades_opened_total counter",
        f"engine_trades_opened_total {_trades_opened}",
        "",
        "# HELP engine_trades_closed_total Total de trades fechados.",
        "# TYPE engine_trades_closed_total counter",
        f"engine_trades_closed_total {_trades_closed}",
        "",
        "# HELP engine_trades_won_total Total de trades com lucro.",
        "# TYPE engine_trades_won_total counter",
        f"engine_trades_won_total {_trades_won}",
        "",
        "# HELP engine_trades_lost_total Total de trades com prejuízo.",
        "# TYPE engine_trades_lost_total counter",
        f"engine_trades_lost_total {_trades_lost}",
        "",
        "# HELP engine_pnl_total PnL total (R$).",
        "# TYPE engine_pnl_total gauge",
        f"engine_pnl_total {_pnl_total:.2f}",
    ]
    for symbol, pnl in _pnl_by_symbol.items():
        lines.append(f'engine_pnl_by_symbol{{symbol="{symbol}"}} {pnl:.2f}')
    for symbol, count in _trades_by_symbol.items():
        lines.append(f'engine_trades_by_symbol{{symbol="{symbol}"}} {count}')
    return "\n".join(lines) + "\n"