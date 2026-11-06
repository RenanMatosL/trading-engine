"""Endpoint `/stream` (F7f) — SSE do status em tempo real.

Empurra o HTML do partial `_status_sse.html` a cada 2s.
Cliente: HTMX com `hx-ext="sse" sse-connect="/stream" sse-swap="message"`.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

from engine.application.status import get_status
from engine.config.presets import load_preset
from engine.config.settings import EngineSettings
from engine.web.deps import get_gateway


log = structlog.get_logger()

router = APIRouter(tags=["stream"])

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Intervalo entre emissões (segundos)
_POLL_INTERVAL = 2.0


async def _render_status(request: Request) -> str:
    """Renderiza o partial `_status_sse.html` como uma string SSE."""
    settings: EngineSettings = request.app.state.settings
    gateway = get_gateway(request)

    # Caso 1: MT5 indisponível
    if gateway is None:
        ctx = {
            "engine_status": "no_mt5",
            "error": "MT5 indisponível. Rode com FakeGateway ou abra o MT5.",
        }
        # Jinja renderiza o partial sem precisar do request
        return _sse_frame(templates.get_template("_status_sse.html").render(ctx))

    # Caso 2: MT5 disponível
    try:
        preset = load_preset(settings.preset)
        status = get_status(gateway, settings.mt5.symbol, preset)
    except Exception as exc:  # noqa: BLE001
        log.error("stream_status_falhou", erro=str(exc))
        ctx = {"engine_status": "error", "error": str(exc)}
        return _sse_frame(templates.get_template("_status_sse.html").render(ctx))

    detector = None
    if status.reading is not None:
        detector = {
            "zscore": status.reading.zscore,
            "mean": status.reading.mean,
            "std": status.reading.std,
            "volume": status.reading.volume,
            "is_signal": status.reading.is_signal,
        }

    ctx = {
        "engine_status": "ready",
        "account": {
            "login": status.account.login,
            "server": status.account.server,
            "balance": status.account.balance,
            "currency": status.account.currency,
        },
        "symbol": status.symbol,
        "bars_loaded": status.bars_loaded,
        "last_bar_time": status.last_bar_time,
        "last_close": status.last_close,
        "detector": detector,
    }
    return _sse_frame(templates.get_template("_status_sse.html").render(ctx))


def _sse_frame(html: str) -> str:
    """Formata HTML como um frame SSE.

    O protocolo SSE exige que cada linha comece com `data: `.
    Como o HTML tem várias linhas, quebramos cada uma em um `data: `.
    """
    lines = html.splitlines()
    data = "\n".join(f"data: {line}" for line in lines)
    return f"{data}\n\n"


@router.get("/stream")
async def stream_status(request: Request):
    """SSE: emite o status do motor a cada 2s."""
    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    log.info("stream_cliente_desconectou")
                    break
                try:
                    yield await _render_status(request)
                except Exception as exc:  # noqa: BLE001
                    log.error("stream_emit_falhou", erro=str(exc))
                    yield _sse_frame(f"<article class='card'><p>Erro: {exc}</p></article>")
                await asyncio.sleep(_POLL_INTERVAL)
        except asyncio.CancelledError:
            log.info("stream_cancelado")
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )