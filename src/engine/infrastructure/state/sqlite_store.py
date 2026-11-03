"""StateStore SQLite — persistência em disco (F3c).

Schema criado automaticamente no `__init__` (CREATE TABLE IF NOT EXISTS).
Datas em ISO 8601 UTC. Enum `RegionPhase` serializado como string.

Não usa ORM: só `sqlite3` da stdlib. Simples, rápido, sem dependência extra.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from engine.domain.state.store import SessionSnapshot, StateStore
from engine.domain.strategy.location import (
    RegionPhase,
    RegionState,
    TradeLocation,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS regions (
    bar_time TEXT PRIMARY KEY,
    high REAL NOT NULL,
    low REAL NOT NULL,
    volume REAL NOT NULL,
    big_candle INTEGER NOT NULL,
    phase TEXT NOT NULL,
    is_buy INTEGER NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    broken_time TEXT,
    rearmed_once INTEGER NOT NULL
);
"""


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _iso_to_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class SqliteStateStore:
    """Implementação SQLite de `StateStore`."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ----------------------------------------------------------------
    # Session state (key/value JSON)
    # ----------------------------------------------------------------
    def save_session(self, snapshot: SessionSnapshot) -> None:
        payload = {
            "last_sl_time": _dt_to_iso(snapshot.last_sl_time),
            "trades_today": snapshot.trades_today,
            "current_day": _dt_to_iso(snapshot.current_day),
            "current_entry_region": _dt_to_iso(snapshot.current_entry_region),
            "current_entry_position": snapshot.current_entry_position,
            # F5e
            "current_entry_price": snapshot.current_entry_price,
            "current_is_buy": snapshot.current_is_buy,
            "reentry_armed": snapshot.reentry_armed,
            "reentry_done": snapshot.reentry_done,
            "partials_filled": list(snapshot.partials_filled),
        }
        now = datetime.now(tz=timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO session_state (key, value, updated_at) "
            "VALUES (?, ?, ?)",
            ("snapshot", json.dumps(payload), now),
        )
        self._conn.commit()

    def load_session(self) -> SessionSnapshot | None:
        row = self._conn.execute(
            "SELECT value FROM session_state WHERE key = 'snapshot'"
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["value"])
        return SessionSnapshot(
            last_sl_time=_iso_to_dt(payload.get("last_sl_time")),
            trades_today=int(payload.get("trades_today", 0)),
            current_day=_iso_to_dt(payload.get("current_day")),
            current_entry_region=_iso_to_dt(payload.get("current_entry_region")),
            current_entry_position=payload.get("current_entry_position"),
            # F5e
            current_entry_price=payload.get("current_entry_price"),
            current_is_buy=payload.get("current_is_buy"),
            reentry_armed=bool(payload.get("reentry_armed", False)),
            reentry_done=bool(payload.get("reentry_done", False)),
            partials_filled=tuple(payload.get("partials_filled", [])),
        )

    # ----------------------------------------------------------------
    # Regions
    # ----------------------------------------------------------------
    def save_regions(self, regions: list[RegionState]) -> None:
        # Simplest strategy: DELETE + INSERT (idempotente).
        # Em F5, se ficar caro, vira diff.
        self._conn.execute("DELETE FROM regions")
        for r in regions:
            self._conn.execute(
                "INSERT INTO regions "
                "(bar_time, high, low, volume, big_candle, phase, is_buy, "
                " stop_loss, take_profit, broken_time, rearmed_once) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _dt_to_iso(r.location.bar_time),
                    r.location.high,
                    r.location.low,
                    r.location.volume,
                    int(r.location.big_candle),
                    r.phase.value,
                    int(r.is_buy),
                    r.stop_loss,
                    r.take_profit,
                    _dt_to_iso(r.broken_time),
                    int(r.rearmed_once),
                ),
            )
        self._conn.commit()

    def load_regions(self) -> list[RegionState]:
        rows = self._conn.execute("SELECT * FROM regions ORDER BY bar_time").fetchall()
        out: list[RegionState] = []
        for row in rows:
            bar_time = _iso_to_dt(row["bar_time"])
            if bar_time is None:
                continue
            loc = TradeLocation(
                bar_time=bar_time,
                high=float(row["high"]),
                low=float(row["low"]),
                volume=float(row["volume"]),
                big_candle=bool(row["big_candle"]),
            )
            out.append(
                RegionState(
                    location=loc,
                    phase=RegionPhase(row["phase"]),
                    is_buy=bool(row["is_buy"]),
                    stop_loss=float(row["stop_loss"]),
                    take_profit=float(row["take_profit"]),
                    broken_time=_iso_to_dt(row["broken_time"]),
                    rearmed_once=bool(row["rearmed_once"]),
                )
            )
        return out

    # ----------------------------------------------------------------
    def clear(self) -> None:
        self._conn.execute("DELETE FROM session_state")
        self._conn.execute("DELETE FROM regions")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()