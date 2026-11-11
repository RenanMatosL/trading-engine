"""Endpoint `/api/trades` (F7b-2).

Retorna os últimos trades do SQLite (`engine.db`).
Negocia JSON (API) ou HTML (HTMX), igual ao `/api/status`.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import timezone

from engine.config.settings import EngineSettings
from engine.domain.state.store import TradeRecord
from engine.infrastructure.state.sqlite_store import SqliteStateStore
from engine.web.schemas import TradeSchema
from engine.web.deps import get_gateway


log = structlog.get_logger()

router = APIRouter(tags=["trades"])

# Templates (para HTMX)
_TEMPLATES_DIR = __import__("pathlib").Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _get_store(request: Request) -> SqliteStateStore:
    """Retorna o state store do app (ou cria um novo)."""
    settings: EngineSettings = request.app.state.settings
    db_path = getattr(request.app.state, "db_path", "engine.db")
    return SqliteStateStore(db_path)


@router.get("/api/trades")
async def list_trades(request: Request, limit: int = 50):
    limit = max(1, min(limit, 500))
    store = _get_store(request)
    try:
        trades = store.list_trades(limit=limit)
    finally:
        store.close()

    is_htmx = request.headers.get("hx-request") == "true"

    if is_htmx:
        trades_formatados = []
        for t in trades:
            dt_utc = t.region_bar_time
            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            
            # A MÁGICA ACONTECE AQUI: Converte UTC para o fuso local do Windows
            dt_local = dt_utc.astimezone()
            
            trades_formatados.append({
                "id": t.id,
                "region_bar_time_str": dt_local.strftime("%d/%m/%Y %H:%M"), 
                "is_buy": t.is_buy,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_money": t.pnl_money,
                "exit_reason": t.exit_reason,
            })
            
        return templates.TemplateResponse(
            request=request,
            name="_trades.html",
            context={"trades": trades_formatados},
        )

    return [_to_schema(t) for t in trades]


@router.get("/api/history_markers")
async def get_history_markers(request: Request):
    """Retorna todos os gatilhos salvos no banco (para pintar no gráfico)."""
    store = _get_store(request)
    try:
        trades = store.list_trades(limit=1000)
    finally:
        store.close()

    markers = []
    for t in trades:
        if t.exit_reason == "trigger_candle":
            # Formata a hora para o padrão do Lightweight Charts
            trigger_ts = int(t.region_bar_time.timestamp())
            markers.append({
                "time": trigger_ts,
                "position": "aboveBar",  
                "color": "#9c27b0",      
                "shape": "arrowDown",    
                "text": "Gatilho",
            })
    return markers


@router.get("/api/trades/log")
async def get_trades_log(request: Request):
    """Retorna o log detalhado de trades REAIS (esconde os gatilhos visuais)."""
    store = _get_store(request)
    try:
        trades = store.list_trades(limit=100)
    finally:
        store.close()

    out = []
    for t in trades:
        if t.exit_reason == "trigger_candle":
            continue

        dt_utc = t.region_bar_time
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        
        # Converte UTC para o fuso local do Windows
        dt_local = dt_utc.astimezone()
        
        out.append({
            "region_bar_time": dt_local.strftime("%d/%m/%Y %H:%M"),
            "is_buy": t.is_buy,
            "entry_time": t.entry_time.isoformat(),
            "entry_price": t.entry_price,
            "exit_time": t.exit_time.isoformat(),
            "exit_price": t.exit_price,
            "stop_loss": t.stop_loss,
            "take_profit": t.take_profit,
            "sl_points": (t.entry_price - t.stop_loss) if t.is_buy else (t.stop_loss - t.entry_price),
            "tp_points": (t.take_profit - t.entry_price) if t.is_buy else (t.entry_price - t.take_profit),
            "initial_volume": t.initial_volume,
            "pnl_points": t.pnl_points,
            "pnl_money": t.pnl_money,
            "exit_reason": t.exit_reason,
        })
    return out


@router.get("/api/candles")
async def get_candles(request: Request, limit: int = 1500):
    """Retorna os últimos N candles para renderizar o gráfico no Dashboard."""
    gateway = get_gateway(request)
    if not gateway:
        raise HTTPException(status_code=503, detail="MT5 indisponível")

    try:
        settings = request.app.state.settings
        bars = gateway.closed_bars(settings.mt5.symbol, "M1", limit)
        
        candles = []
        for bar in bars:
            candles.append({
                "time": int(bar.time.timestamp()),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
            })
        
        candles.sort(key=lambda x: x["time"])
        return {"candles": candles}
    except Exception as exc:
        log.error("api_candles_falhou", erro=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/active_trade")
async def get_active_trade(request: Request):
    """Retorna o status da operação atual (Lê do SQLite)."""
    store = _get_store(request)
    try:
        trades = store.list_trades(limit=1)
    finally:
        store.close()

    if not trades:
        return {
            "status": "Aguardando Sinal (Sem histórico)",
            "direction": "—",
            "candle_time": "—",
            "candle_high": 0.0,
            "candle_low": 0.0,
            "entry": 0.0,
            "sl": 0.0,
            "tp": 0.0,
        }

    last_trade = trades[0]
    
    dt_utc = last_trade.region_bar_time
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        
    # Converte UTC para o fuso local
    dt_local = dt_utc.astimezone()
    horario_formatado = dt_local.strftime("%H:%M")

    if last_trade.exit_reason == "trigger_candle":
        return {
            "status": "Monitorando Pullback",
            "direction": "COMPRA" if last_trade.is_buy else "VENDA",
            "candle_time": horario_formatado,
            "candle_high": last_trade.take_profit,
            "candle_low": last_trade.stop_loss,
            "entry": last_trade.entry_price,
            "sl": last_trade.stop_loss,
            "tp": last_trade.take_profit,
        }

    return {
        "status": "Monitorando Pullback" if last_trade.exit_reason == "open" else "Aguardando Novo Sinal",
        "direction": "COMPRA" if last_trade.is_buy else "VENDA",
        "candle_time": horario_formatado,
        "candle_high": last_trade.take_profit,
        "candle_low": last_trade.stop_loss,
        "entry": last_trade.entry_price,
        "sl": last_trade.stop_loss,
        "tp": last_trade.take_profit,
    }


def _to_schema(trade: TradeRecord) -> TradeSchema:
    """Converte o TradeRecord para o Schema JSON."""
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