"""Popula o engine.db com 2 trades fake (F7b-2, para testar o dashboard)."""
from datetime import datetime, timezone, timedelta

from engine.infrastructure.state.sqlite_store import SqliteStateStore
from engine.domain.state.store import TradeRecord


t = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)
store = SqliteStateStore("engine.db")

store.save_trade(TradeRecord(
    id=None, region_bar_time=t, is_buy=True,
    entry_time=t, entry_price=1100.0,
    exit_time=t + timedelta(minutes=5), exit_price=1700.0,
    stop_loss=800.0, take_profit=1700.0, initial_volume=6.0,
    pnl_points=600.0, pnl_money=3600.0, exit_reason="take_profit",
))

store.save_trade(TradeRecord(
    id=None, region_bar_time=t, is_buy=False,
    entry_time=t + timedelta(minutes=10), entry_price=1200.0,
    exit_time=t + timedelta(minutes=15), exit_price=1400.0,
    stop_loss=1400.0, take_profit=800.0, initial_volume=6.0,
    pnl_points=-200.0, pnl_money=-1200.0, exit_reason="stop_loss",
))

store.close()
print("OK: 2 trades inseridos em engine.db")