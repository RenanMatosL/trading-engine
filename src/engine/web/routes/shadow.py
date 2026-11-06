"""Endpoint `/api/shadow` (F7e).

Compara deals do EA (MQL5) com deals do Python (motor) numa janela
de tempo. Read-only: não coloca ordens.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from engine.application.shadow import ShadowComparer
from engine.web.deps import get_gateway


log = structlog.get_logger()

router = APIRouter(prefix="/api/shadow", tags=["shadow"])

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@dataclass(frozen=True, slots=True)
class _ShadowTrade:
    """Wrapper leve para simular um TradeIntent para o ShadowComparer.
    
    O comparador só precisa de `bar_time`, `is_buy` e `entry_price`.
    Isso evita termos que inventar `RegionState`, `volume` ou `partials`.
    """
    bar_time: datetime
    is_buy: bool
    entry_price: float


#+------------------------------------------------------------------+
#| GET /api/shadow  — form inicial                                  |
#+------------------------------------------------------------------+
@router.get("")
async def get_shadow_form(request: Request):
    """Retorna o formulário de shadow (HTML) para o HTMX carregar."""
    return templates.TemplateResponse(
        request=request,
        name="_shadow.html",
        context={"report": None, "error": None, "form": None},
    )


#+------------------------------------------------------------------+
#| POST /api/shadow — compara EA × Python                           |
#+------------------------------------------------------------------+
@router.post("")
async def run_shadow(
    request: Request,
    ea_magic: int = Form(...),
    py_magic: int = Form(0),
    duration_min: int = Form(60),
    tolerance_points: float = Form(2.0),
    symbol: str = Form(""),
):
    """Coleta deals do EA e do Python e compara."""
    is_htmx = request.headers.get("hx-request") == "true"

    form_data = {
        "ea_magic": ea_magic,
        "py_magic": py_magic,
        "duration_min": duration_min,
        "tolerance_points": tolerance_points,
        "symbol": symbol,
    }

    # Validações
    if ea_magic <= 0:
        return _error("ea_magic deve ser > 0", request, is_htmx, form_data)
    if py_magic and py_magic == ea_magic:
        return _error(
            "py_magic não pode ser igual a ea_magic", request, is_htmx, form_data
        )
    if duration_min <= 0 or duration_min > 10080:  # 7 dias
        return _error(
            "duration_min deve estar entre 1 e 10080", request, is_htmx, form_data
        )
    if tolerance_points < 0:
        return _error(
            "tolerance_points deve ser >= 0", request, is_htmx, form_data
        )

    gateway = get_gateway(request)
    if gateway is None:
        return _error(
            "MT5 indisponível. Abra o MT5 ou rode com FakeGateway.",
            request, is_htmx, form_data,
        )

    # Janela de comparação
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(minutes=duration_min)
    symbol_filter = symbol.strip() or None
    py_magic_eff = py_magic if py_magic > 0 else (ea_magic + 1)

    # Coleta deals
    try:
        ea_deals = gateway.history_deals(
            since=since, symbol=symbol_filter, magic=ea_magic
        )
        py_deals = gateway.history_deals(
            since=since, symbol=symbol_filter, magic=py_magic_eff
        )
    except Exception as exc:  # noqa: BLE001
        log.error("shadow_history_falhou", erro=str(exc))
        return _error(f"Falha ao ler deals: {exc}", request, is_htmx, form_data)

    # Converte deals do Python usando o wrapper leve
    py_trades: list[_ShadowTrade] = []
    for d in py_deals:
        if not d.is_entry:
            continue
        py_trades.append(_ShadowTrade(
            bar_time=d.time,
            is_buy=d.is_buy,
            entry_price=d.price,
        ))

    # Compara
    try:
        report = ShadowComparer().compare(
            ea_deals,
            py_trades,
            start=since,
            end=now,
            tolerance_points=tolerance_points,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("shadow_compare_falhou", erro=str(exc))
        return _error(f"Falha na comparação: {exc}", request, is_htmx, form_data)

    log.info(
        "shadow_report",
        matched=report.matched,
        ea_only=report.ea_only,
        py_only=report.py_only,
        mismatches=report.mismatches,
        match_rate=report.match_rate,
    )

    report_dict = report.to_dict()

    if is_htmx:
        return templates.TemplateResponse(
            request=request,
            name="_shadow.html",
            context={"report": report_dict, "error": None, "form": form_data},
        )
    return JSONResponse(content=report_dict)


def _error(
    msg: str,
    request: Request,
    is_htmx: bool,
    form_data: dict | None = None,
) -> HTMLResponse | JSONResponse:
    if is_htmx:
        return templates.TemplateResponse(
            request=request,
            name="_shadow.html",
            context={"report": None, "error": msg, "form": form_data},
            status_code=400,
        )
    return JSONResponse(status_code=400, content={"error": msg})