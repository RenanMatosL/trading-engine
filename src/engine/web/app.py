"""FastAPI app do Trading Engine (F7a)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from engine.application.status import get_status
from engine.config.presets import load_preset
from engine.config.settings import EngineSettings
from engine.web.deps import get_gateway, get_settings
from engine.web.schemas import (
    AccountSchema,
    DetectorSchema,
    StatusResponse,
)


log = structlog.get_logger()

_BASE_DIR = Path(__file__).parent
_TEMPLATES_DIR = _BASE_DIR / "templates"
_STATIC_DIR = _BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from engine.web.deps import shutdown_gateway, startup_gateway

    settings = EngineSettings()
    app.state.settings = settings
    app.state.gateway = await startup_gateway(settings)
    try:
        yield
    finally:
        await shutdown_gateway(app.state.gateway)


app = FastAPI(title="Trading Engine", version="0.1.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


#+------------------------------------------------------------------+
#| Rotas HTML                                                       |
#+------------------------------------------------------------------+
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"title": "Dashboard"},
    )


#+------------------------------------------------------------------+
#| Rotas API (JSON / HTML negociado)                                |
#+------------------------------------------------------------------+
@app.get("/api/status")
async def api_status(request: Request):
    settings: EngineSettings = get_settings(request)
    gateway = get_gateway(request)
    is_htmx = request.headers.get("hx-request") == "true"

    # Caso 1: MT5 indisponível
    if gateway is None:
        err = "MT5 indisponível. Rode com FakeGateway ou abra o MT5."
        if is_htmx:
            return templates.TemplateResponse(
                request=request,
                name="_status.html",
                context={"engine_status": "no_mt5", "error": err},
            )
        return StatusResponse(
            account=AccountSchema(login=0, server="—", balance=0.0, currency="—"),
            symbol=settings.mt5.symbol, bars_loaded=0,
            last_bar_time="—", last_close=0.0,
            engine_status="no_mt5", error=err,
        )

    # Caso 2: MT5 disponível
    try:
        preset = load_preset(settings.preset)
        status = get_status(gateway, settings.mt5.symbol, preset)
    except Exception as exc:  # noqa: BLE001
        log.error("api_status_falhou", erro=str(exc))
        if is_htmx:
            return templates.TemplateResponse(
                request=request,
                name="_status.html",
                context={"engine_status": "error", "error": str(exc)},
            )
        return StatusResponse(
            account=AccountSchema(login=0, server="—", balance=0.0, currency="—"),
            symbol=settings.mt5.symbol, bars_loaded=0,
            last_bar_time="—", last_close=0.0,
            engine_status="error", error=str(exc),
        )

    detector = None
    if status.reading is not None:
        detector = DetectorSchema(
            zscore=status.reading.zscore, mean=status.reading.mean,
            std=status.reading.std, volume=status.reading.volume,
            is_signal=status.reading.is_signal,
        )

    response = StatusResponse(
        account=AccountSchema(
            login=status.account.login, server=status.account.server,
            balance=status.account.balance, currency=status.account.currency,
        ),
        symbol=status.symbol, bars_loaded=status.bars_loaded,
        last_bar_time=status.last_bar_time, last_close=status.last_close,
        detector=detector, regions_count=0, regions=[],
        engine_status="ready",
    )

    if is_htmx:
        return templates.TemplateResponse(
            request=request,
            name="_status.html",
            context=response.model_dump(mode="json"),
        )

    return response


#+------------------------------------------------------------------+
#| Static (CSS/JS)                                                  |
#+------------------------------------------------------------------+
if _STATIC_DIR.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")