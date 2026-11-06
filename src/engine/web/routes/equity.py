"""Endpoint `/api/equity` (F7b-2).

Retorna a equity curve do SQLite (`engine.db`).
Negocia JSON (API) ou HTML (HTMX).
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from engine.config.settings import EngineSettings
from engine.infrastructure.state.sqlite_store import SqliteStateStore
from engine.web.schemas import EquityPointSchema


log = structlog.get_logger()

router = APIRouter(prefix="/api/equity", tags=["equity"])

_TEMPLATES_DIR = __import__("pathlib").Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("")
async def get_equity(request: Request, limit: int = 1000):
    """Retorna a equity curve.

    Query params:
      - limit: máximo de pontos (default: 1000, max: 10000)
    """
    limit = max(1, min(limit, 10_000))

    settings: EngineSettings = request.app.state.settings
    db_path = getattr(request.app.state, "db_path", "engine.db")
    store = SqliteStateStore(db_path)
    try:
        curve = store.list_equity(limit=limit)
    finally:
        store.close()

    points = [
        EquityPointSchema(time=ts.isoformat(), balance=balance)
        for ts, balance in curve
    ]

    is_htmx = request.headers.get("hx-request") == "true"
    if is_htmx:
        return templates.TemplateResponse(
            request=request,
            name="_equity.html",
            context={
                "points": [p.model_dump() for p in points],
                "n_points": len(points),
            },
        )

    return points