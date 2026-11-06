"""Golden tests dos endpoints web (F7b-2)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.domain.state.store import TradeRecord
from engine.infrastructure.state.sqlite_store import SqliteStateStore
from engine.web.app import app


T0 = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Cria o TestClient com DB temporário (sem MT5)."""
    db_path = tmp_path / "test.db"

    # 1. Popula o DB com 2 trades (antes do TestClient)
    store = SqliteStateStore(db_path)
    store.save_trade(TradeRecord(
        id=None, region_bar_time=T0, is_buy=True,
        entry_time=T0, entry_price=1100.0,
        exit_time=T0.replace(hour=10), exit_price=1700.0,
        stop_loss=800.0, take_profit=1700.0, initial_volume=6.0,
        pnl_points=600.0, pnl_money=3600.0, exit_reason="take_profit",
    ))
    store.save_trade(TradeRecord(
        id=None, region_bar_time=T0, is_buy=False,
        entry_time=T0, entry_price=1200.0,
        exit_time=T0.replace(hour=11), exit_price=1400.0,
        stop_loss=1400.0, take_profit=800.0, initial_volume=6.0,
        pnl_points=-200.0, pnl_money=-1200.0, exit_reason="stop_loss",
    ))
    store.close()

    # 2. Sobrescreve db_path DEPOIS do lifespan rodar
    with TestClient(app) as c:
        app.state.db_path = str(db_path)
        yield c


#+------------------------------------------------------------------+
#| F7b-2 — /api/trades                                              |
#+------------------------------------------------------------------+
def test_api_trades_json(client):
    """GET /api/trades (sem HX-Request) retorna JSON."""
    r = client.get("/api/trades")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    # Mais recente primeiro (exit_time DESC)
    assert data[0]["exit_reason"] == "stop_loss"
    assert data[1]["exit_reason"] == "take_profit"


def test_api_trades_html(client):
    """GET /api/trades (com HX-Request) retorna HTML."""
    r = client.get("/api/trades", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "take_profit" in r.text or "stop_loss" in r.text


#+------------------------------------------------------------------+
#| F7b-2 — /api/equity                                              |
#+------------------------------------------------------------------+
def test_api_equity_json(client):
    """GET /api/equity (sem HX-Request) retorna JSON."""
    r = client.get("/api/equity")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    # Balance acumulado: 100_000 + 3600 = 103_600; + (-1200) = 102_400
    # Ordem cronológica (exit_time ASC)
    assert data[0]["balance"] == 103_600.0
    assert data[1]["balance"] == 102_400.0


def test_api_equity_html(client):
    """GET /api/equity (com HX-Request) retorna HTML."""
    r = client.get("/api/equity", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


#+------------------------------------------------------------------+
#| F7b-2 — sanity                                                   |
#+------------------------------------------------------------------+
def test_api_trades_limit(client):
    """?limit=1 retorna só 1 trade."""
    r = client.get("/api/trades?limit=1")
    assert r.status_code == 200
    assert len(r.json()) == 1