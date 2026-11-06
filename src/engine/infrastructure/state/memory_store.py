"""StateStore in-memory — testes e desenvolvimento."""
from __future__ import annotations

import copy

from engine.domain.state.store import (
    SessionSnapshot,
    StateStore,
    TradeRecord,
)
from engine.domain.strategy.location import RegionState


class InMemoryStateStore:
    """Implementação simples de `StateStore` sem persistência real."""

    def __init__(self) -> None:
        self._snapshot: SessionSnapshot | None = None
        self._regions: list[RegionState] = []
        self._trades: list[TradeRecord] = []
        self._next_id: int = 1
        self._initial_balance: float = 100_000.0

    # --- Session ---
    def save_session(self, snapshot: SessionSnapshot) -> None:
        self._snapshot = snapshot

    def load_session(self) -> SessionSnapshot | None:
        return self._snapshot

    # --- Regions ---
    def save_regions(self, regions: list[RegionState]) -> None:
        self._regions = [copy.deepcopy(r) for r in regions]

    def load_regions(self) -> list[RegionState]:
        return [copy.deepcopy(r) for r in self._regions]

    # --- Trades (F7b-1) ---
    def save_trade(self, trade: TradeRecord) -> int:
        """Grava trade e retorna o ID gerado."""
        new_id = self._next_id
        self._next_id += 1
        # Cria uma cópia com id setado (TradeRecord é frozen)
        stored = TradeRecord(
            id=new_id,
            region_bar_time=trade.region_bar_time,
            is_buy=trade.is_buy,
            entry_time=trade.entry_time,
            entry_price=trade.entry_price,
            exit_time=trade.exit_time,
            exit_price=trade.exit_price,
            stop_loss=trade.stop_loss,
            take_profit=trade.take_profit,
            initial_volume=trade.initial_volume,
            pnl_points=trade.pnl_points,
            pnl_money=trade.pnl_money,
            exit_reason=trade.exit_reason,
        )
        self._trades.append(stored)
        return new_id

    def list_trades(self, limit: int = 50) -> list[TradeRecord]:
        """Últimos trades (mais recentes primeiro)."""
        return list(reversed(self._trades[-limit:])) if self._trades else []

    def list_equity(self, limit: int = 1000) -> list[tuple[datetime, float]]:
        """Equity curve derivada dos trades (PnL acumulado)."""
        # No InMemoryStateStore, derivamos do _trades + balance inicial
        if not self._trades:
            return []
        balance = self._initial_balance
        curve: list[tuple[datetime, float]] = []
        # Ordena por exit_time
        sorted_trades = sorted(self._trades, key=lambda t: t.exit_time)
        for t in sorted_trades[-limit:]:
            balance += t.pnl_money
            curve.append((t.exit_time, balance))
        return curve

    # --- Clear ---
    def clear(self) -> None:
        self._snapshot = None
        self._regions = []
        self._trades = []
        self._next_id = 1