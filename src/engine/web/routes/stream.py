"""Endpoint `/stream` (F7f) — SSE do status em tempo real (JSON)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from engine.application.status import get_status
from engine.config.presets import load_preset
from engine.config.settings import EngineSettings
from engine.domain.strategy.detector import VolumeStdDetector
from engine.infrastructure.state.sqlite_store import SqliteStateStore
from engine.web.deps import get_gateway


log = structlog.get_logger()
router = APIRouter(tags=["stream"])

_POLL_INTERVAL = 2.0


def _get_active_trade_info(request: Request) -> dict:
    """Busca na sessão do motor as informações do trade atual."""
    try:
        store = SqliteStateStore(request.app.state.db_path)
        trades = store.list_trades(limit=1)
        store.close()
        
        if trades and trades[0].exit_reason == "open":
            t = trades[0]
            return {
                "status": "Monitorando Pullback",
                "direction": "COMPRA" if t.is_buy else "VENDA",
                "candle_time": t.region_bar_time.strftime("%d/%m/%Y %H:%M"),
                "entry": t.entry_price,
                "sl": t.stop_loss,
                "tp": t.take_profit,
            }
    except Exception:
        pass
    
    return {
        "status": "Aguardando Sinal...",
        "direction": "—",
        "candle_time": "—",
        "entry": 0.0,
        "sl": 0.0,
        "tp": 0.0,
    }

async def _render_status_json(request: Request) -> str:
    """Gera o payload JSON para o SSE."""
    settings: EngineSettings = request.app.state.settings
    gateway = get_gateway(request)

    if gateway is None:
        return _sse_frame(json.dumps({"status": "no_mt5"}))

    try:
        preset = load_preset(settings.preset)
        account = gateway.account()
        tick = gateway.symbol_info_tick(settings.mt5.symbol)
        
        # Puxa os últimos 181 candles para calcular o Z-score
        bars = gateway.closed_bars(settings.mt5.symbol, preset.detector.timeframe, preset.detector.length + 1)
        
        # Calcula o detector
        detector_info = None
        if bars and len(bars) >= preset.detector.length:
            det = VolumeStdDetector(
                length=preset.detector.length,
                std_ref=preset.detector.std_ref,
                source=preset.detector.volume_source,
            )
            for b in bars:
                reading = det.on_bar_closed(b)
            
            if reading:
                detector_info = {
                    "zscore": reading.zscore,
                    "mean": reading.mean,
                    "std": reading.std,
                    "volume": reading.volume,
                }

        active = _get_active_trade_info(request)

        payload = {
            "status": "ready",
            "account": {
                "login": account.login,
                "server": account.server,
                "balance": account.balance,
                "currency": account.currency,
            },
            "symbol": settings.mt5.symbol,
            "last_close": tick.bid if tick else 0.0,
            "candles_loaded": len(bars),
            "detector": detector_info,
            "active_trade": active,
        }
        
        return _sse_frame(json.dumps(payload))
    except Exception as exc:
        log.error("stream_error", erro=str(exc))
        return _sse_frame(json.dumps({"status": "error", "msg": str(exc)}))


def _sse_frame(json_str: str) -> str:
    return f"data: {json_str}\n\n"


@router.get("/stream")
async def stream_status(request: Request):
    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                yield await _render_status_json(request)
                await asyncio.sleep(_POLL_INTERVAL)
        except asyncio.CancelledError:
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )