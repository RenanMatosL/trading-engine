"""Endpoint `/api/backtest` (F7d).

Recebe upload de CSV + parâmetros, roda `Backtester` e retorna resultado
(JSON/HTML).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import structlog
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from engine.application.backtester import Backtester
from engine.config.presets import load_preset
from engine.config.settings import EngineSettings
from engine.infrastructure.data.csv_loader import load_bars_csv


log = structlog.get_logger()

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.post("")
async def run_backtest(
    request: Request,
    file: UploadFile = File(...),
    initial_balance: float = Form(100_000.0),
    slippage: float = Form(0.0),
    spread: float = Form(0.0),
    from_date: str = Form(""),
    to_date: str = Form(""),
):
    """Roda backtest sobre CSV uploadado."""
    settings: EngineSettings = request.app.state.settings
    is_htmx = request.headers.get("hx-request") == "true"

    # 1. Salva o CSV temporariamente
    try:
        content = await file.read()
        if not content:
            return _error("Arquivo vazio", request, is_htmx)
    except Exception as exc:  # noqa: BLE001
        return _error(f"Falha ao ler upload: {exc}", request, is_htmx)

    tmp_dir = Path(tempfile.gettempdir())
    tmp_csv = tmp_dir / f"backtest_{file.filename or 'upload.csv'}"
    try:
        tmp_csv.write_bytes(content)
    except Exception as exc:  # noqa: BLE001
        return _error(f"Falha ao salvar upload: {exc}", request, is_htmx)

    # 2. Carrega CSV
    try:
        bars = load_bars_csv(tmp_csv)
    except Exception as exc:  # noqa: BLE001
        return _error(f"CSV inválido: {exc}", request, is_htmx)
    finally:
        try:
            tmp_csv.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    if not bars:
        return _error("CSV vazio ou sem candles", request, is_htmx)

    # 3. Filtra por data (opcional)
    if from_date:
        bars = [b for b in bars if b.time.strftime("%Y-%m-%d") >= from_date]
    if to_date:
        bars = [b for b in bars if b.time.strftime("%Y-%m-%d") <= to_date]

    if not bars:
        return _error("Nenhum candle no período", request, is_htmx)

    # 4. Carrega preset
    try:
        preset = load_preset(settings.preset)
    except Exception as exc:  # noqa: BLE001
        return _error(f"Preset inválido: {exc}", request, is_htmx)

    # 5. Roda backtest
    try:
        bt = Backtester(
            preset,
            initial_balance=initial_balance,
            slippage_points=slippage,
            spread_points=spread,
        )
        result = bt.run(bars)
    except Exception as exc:  # noqa: BLE001
        log.error("backtest_falhou", erro=str(exc))
        return _error(f"Backtest falhou: {exc}", request, is_htmx)

    # 6. Serializa resultado
    stats = result.simulation.stats
    metrics = result.metrics
    summary = {
        "n_bars": result.n_bars,
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "n_trades": int(stats.get("n_trades", 0)),
        "winners": int(stats.get("winners", 0)),
        "losers": int(stats.get("losers", 0)),
        "win_rate": float(stats.get("win_rate", 0.0)),
        "total_pnl": float(stats.get("total_pnl_money", 0.0)),
        "return_pct": float(stats.get("return_pct", 0.0)),
        "sharpe": float(metrics["sharpe"]),
        "max_drawdown_pct": float(metrics["max_drawdown_pct"]),
        "profit_factor": (
            float(metrics["profit_factor"])
            if metrics["profit_factor"] != float("inf") else "inf"
        ),
        "avg_win": float(metrics["avg_win"]),
        "avg_loss": float(metrics["avg_loss"]),
        "total_return_pct": float(metrics["total_return_pct"]),
    }

    # 7. Retorna (HTML ou JSON)
    if is_htmx:
        return templates.TemplateResponse(
            request=request,
            name="_backtest.html",
            context={"result": summary, "error": None},
        )
    return JSONResponse(content=summary)

@router.get("")
async def get_backtest_form(request: Request):
    """Retorna o formulário de backtest (HTML) para o HTMX carregar."""
    return templates.TemplateResponse(
        request=request,
        name="_backtest.html",
        context={"result": None, "error": None},
    )


def _error(
    msg: str, request: Request, is_htmx: bool
) -> HTMLResponse | JSONResponse:
    if is_htmx:
        return templates.TemplateResponse(
            request=request,
            name="_backtest.html",
            context={"result": None, "error": msg},
            status_code=400,
        )
    return JSONResponse(status_code=400, content={"error": msg})