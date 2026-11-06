"""Endpoint `/api/trades` (F7b-2).

Retorna os últimos trades do SQLite (`engine.db`).
Negocia JSON (API) ou HTML (HTMX), igual ao `/api/status`.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from engine.config.settings import EngineSettings
from engine.domain.state.store import TradeRecord
from engine.infrastructure.state.sqlite_store import SqliteStateStore
from engine.web.schemas import TradeSchema


log = structlog.get_logger()

router = APIRouter(prefix="/api/trades", tags=["trades"])

# Templates (para HTMX)
_TEMPLATES_DIR = __import__("pathlib").Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _get_store(request: Request) -> SqliteStateStore:
    """Retorna o state store do app (ou cria um novo)."""
    settings: EngineSettings = request.app.state.settings
    db_path = getattr(request.app.state, "db_path", "engine.db")
    return SqliteStateStore(db_path)


@router.get("")
async def list_trades(request: Request, limit: int = 50):
    """Lista os últimos trades.

    Query params:
      - limit: máximo de trades (default: 50, max: 500)
    """
    limit = max(1, min(limit, 500))

    store = _get_store(request)
    try:
        trades = store.list_trades(limit=limit)
    finally:
        store.close()

    is_htmx = request.headers.get("hx-request") == "true"

    if is_htmx:
        return templates.TemplateResponse(
            request=request,
            name="_trades.html",
            context={"trades": [_to_schema(t) for t in trades]},
        )

    return [_to_schema(t) for t in trades]


def _to_schema(trade: TradeRecord) -> TradeSchema:
    return TradeSchema(
        id=trade.id,
        region_bar_time=trade.region_bar_time.isoformat(),
        is_buy=trade.is_buy,
        entry_time=trade.entry_time.isoformat(),
        entry_price=trade.entry_price,
        exit_time=trade.exit_time.isoformat(),
        exit_price=trade.exit_price,
        stop_loss=trade.stop_loss,
        take_profit=trade.take_profit,
        initial_volume=trade.initial_volume,
        pnl_points=trade.pnl_points,
        pnl_money=trade.pnl_money,
        exit_reason=trade.exit_reason,
    )