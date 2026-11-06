"""Golden tests dos endpoints web (F7b-2)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

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



#+------------------------------------------------------------------+
#| F7c — /api/preset (GET + POST)                                   |
#+------------------------------------------------------------------+
def _preset_dict() -> dict:
    """Preset mínimo válido (para os testes)."""
    from engine.config.presets import (
        DetectorParams, SessionParams, StdDevV510Preset, TimeWindowParams,
    )
    from datetime import time

    return StdDevV510Preset.model_validate({
        "name": "test",
        "strategy": "stddev_v510",
        "detector": DetectorParams(mute_open_min=0).model_dump(mode="json"),
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=time(9, 0), end=time(17, 30)),
        ).model_dump(mode="json"),
    }).model_dump(mode="json")


@pytest.fixture()
def preset_file(tmp_path):
    """Cria um YAML temporário e ajusta `app.state.settings.preset`."""
    yaml_path = tmp_path / "test_preset.yaml"
    yaml_path.write_text(
        yaml.safe_dump(_preset_dict(), sort_keys=False),
        encoding="utf-8",
    )
    # Guarda o path no app
    from engine.config.settings import EngineSettings
    app.state.settings = EngineSettings()
    app.state.preset_path = str(yaml_path)
    yield yaml_path


def test_api_preset_get_json(client, preset_file):
    """GET /api/preset (sem HX) retorna JSON."""
    r = client.get("/api/preset")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "test"
    assert data["detector"]["length"] == 180


def test_api_preset_get_html(client, preset_file):
    """GET /api/preset (com HX) retorna HTML."""
    r = client.get("/api/preset", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_api_preset_post_valido(client, preset_file):
    """POST /api/preset com preset válido salva o YAML."""
    new_preset = _preset_dict()
    new_preset["detector"]["length"] = 200  # muda length

    r = client.post("/api/preset", json=new_preset)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["preset"]["detector"]["length"] == 200

    # YAML atualizado no disco
    saved = yaml.safe_load(preset_file.read_text(encoding="utf-8"))
    assert saved["detector"]["length"] == 200

    # Backup criado
    backup = preset_file.with_suffix(".yaml.bak")
    assert backup.exists()


def test_api_preset_post_invalido_rejeitado(client, preset_file):
    """POST /api/preset com length<2 retorna 400."""
    bad = _preset_dict()
    bad["detector"]["length"] = 1

    r = client.post("/api/preset", json=bad)
    assert r.status_code == 400
    assert "error" in r.json()


def test_api_preset_post_html(client, preset_file):
    """POST /api/preset (com HX) retorna HTML de sucesso."""
    new_preset = _preset_dict()
    new_preset["detector"]["length"] = 150

    r = client.post(
        "/api/preset",
        json=new_preset,
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]