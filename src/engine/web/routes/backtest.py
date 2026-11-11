"""Endpoint `/api/backtest` (F7d + F10).

Recebe upload de CSV + parâmetros, roda `Backtester` e retorna resultado
(JSON/HTML). F10: adiciona `/chart` para visualização gráfica.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import structlog
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from engine.application.backtester import Backtester
from engine.application.metrics import (
    average_win_loss,
    max_drawdown,
    profit_factor,
    sharpe,
    total_return,
    win_rate,
)
from engine.config.presets import load_preset
from engine.config.settings import EngineSettings
from engine.infrastructure.data.csv_loader import load_bars_csv


log = structlog.get_logger()

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


#+------------------------------------------------------------------+
#| Helper: carrega CSV + filtra + roda backtest                     |
#+------------------------------------------------------------------+
def _run_backtest_from_upload(
    request: Request,
    content: bytes,
    filename: str,
    initial_balance: float,
    slippage: float,
    spread: float,
    from_date: str,
    to_date: str,
):
    """Helper compartilhado entre /api/backtest e /api/backtest/chart.

    Retorna (preset, bars, result) ou levanta exceção com mensagem.
    """
    settings: EngineSettings = request.app.state.settings

    # 1. Salva o CSV temporariamente
    tmp_dir = Path(tempfile.gettempdir())
    tmp_csv = tmp_dir / f"backtest_{filename or 'upload.csv'}"
    try:
        tmp_csv.write_bytes(content)
    except Exception as exc:
        raise RuntimeError(f"Falha ao salvar upload: {exc}") from exc

    # 2. Carrega CSV
    try:
        bars = load_bars_csv(tmp_csv)
    except Exception as exc:
        raise RuntimeError(f"CSV inválido: {exc}") from exc
    finally:
        try:
            tmp_csv.unlink(missing_ok=True)
        except Exception:
            pass

    if not bars:
        raise RuntimeError("CSV vazio ou sem candles")

    # 3. Filtra por data (opcional)
    if from_date:
        bars = [b for b in bars if b.time.strftime("%Y-%m-%d") >= from_date]
    if to_date:
        bars = [b for b in bars if b.time.strftime("%Y-%m-%d") <= to_date]
    if not bars:
        raise RuntimeError("Nenhum candle no período")

    # 4. Carrega preset
    try:
        preset_path = getattr(request.app.state, "preset_path", None)
        if preset_path is None:
            preset_path = settings.preset
        preset = load_preset(Path(preset_path).resolve())
    except Exception as exc:
        raise RuntimeError(f"Preset inválido: {exc}") from exc

    # 5. Roda backtest
    try:
        bt = Backtester(
            preset,
            initial_balance=initial_balance,
            slippage_points=slippage,
            spread_points=spread,
        )
        result = bt.run(bars)
    except Exception as exc:
        raise RuntimeError(f"Backtest falhou: {exc}") from exc

    return preset, bars, result


#+------------------------------------------------------------------+
#| Helper: serializa um Trade para JSON                             |
#+------------------------------------------------------------------+
def _serialize_trade(trade) -> dict:
    """Serializa um SimulatedTrade para JSON (usado no /chart)."""
    return {
        "entry_time": trade.entry_time.isoformat(),
        "exit_time": trade.entry_time.isoformat() if not trade.fills else trade.fills[-1].time.isoformat(),
        "is_buy": trade.is_buy,
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss,
        "take_profit": trade.take_profit,
        "exit_reason": trade.exit_reason.value,
        "pnl_points": trade.pnl_points,
        "pnl_money": trade.pnl_money,
        "initial_volume": trade.initial_volume,
    }


#+------------------------------------------------------------------+
#| POST /api/backtest — resultado numérico                          |
#+------------------------------------------------------------------+
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
    is_htmx = request.headers.get("hx-request") == "true"

    try:
        content = await file.read()
        if not content:
            return _error("Arquivo vazio", request, is_htmx)
    except Exception as exc:  # noqa: BLE001
        return _error(f"Falha ao ler upload: {exc}", request, is_htmx)

    try:
        preset, bars, result = _run_backtest_from_upload(
            request, content, file.filename or "upload.csv",
            initial_balance, slippage, spread, from_date, to_date,
        )
    except RuntimeError as exc:
        return _error(str(exc), request, is_htmx)

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


#+------------------------------------------------------------------+
#| POST /api/backtest/chart — dados para o gráfico de candles (F10) |
#+------------------------------------------------------------------+
@router.post("/chart")
async def run_backtest_chart(
    request: Request,
    file: UploadFile = File(...),
    initial_balance: float = Form(100_000.0),
    slippage: float = Form(0.0),
    spread: float = Form(0.0),
    from_date: str = Form(""),
    to_date: str = Form(""),
):
    """Roda backtest e retorna JSON com candles + markers para o gráfico."""
    try:
        content = await file.read()
        if not content:
            return JSONResponse(status_code=400, content={"error": "Arquivo vazio"})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": f"Falha ao ler upload: {exc}"})

    try:
        preset, bars, result = _run_backtest_from_upload(
            request, content, file.filename or "upload.csv",
            initial_balance, slippage, spread, from_date, to_date,
        )
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    # 1. Converte candles + volumes
    candles = []
    volumes = []
    for bar in bars:
        ts = int(bar.time.timestamp())
        candles.append({
            "time": ts,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
        })
        vol_color = "rgba(38, 166, 154, 0.5)" if bar.close >= bar.open else "rgba(239, 83, 80, 0.5)"
        vol_value = bar.volume(preset.detector.volume_source) if hasattr(bar, "volume") else 0.0
        volumes.append({
            "time": ts,
            "value": float(vol_value),
            "color": vol_color,
        })

    # 2. Converte trades para markers
    markers = []
    for trade in result.simulation.trades:
        entry_ts = int(trade.entry_time.timestamp())
        markers.append({
            "time": entry_ts,
            "position": "belowBar" if trade.is_buy else "aboveBar",
            "color": "green" if trade.is_buy else "red",
            "shape": "arrowUp" if trade.is_buy else "arrowDown",
            "text": f"{'BUY' if trade.is_buy else 'SELL'} {trade.initial_volume:.0f}",
        })
        if trade.fills:
            exit_fill = trade.fills[-1]
            exit_ts = int(exit_fill.time.timestamp())
            exit_color = "green" if trade.pnl_money > 0 else "red"
            markers.append({
                "time": exit_ts,
                "position": "aboveBar" if trade.is_buy else "belowBar",
                "color": exit_color,
                "shape": "circle",
                "text": f"{trade.exit_reason.value} {trade.pnl_points:+.0f}pts",
            })
    markers.sort(key=lambda m: m["time"])

    # 3. Summary (métricas para o card verde)
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

    return JSONResponse(content={
        "candles": candles,
        "volumes": volumes,
        "markers": markers,
        "summary": summary,
    })


#+------------------------------------------------------------------+
#| GET /api/backtest — formulário inicial                           |
#+------------------------------------------------------------------+
@router.get("")
async def get_backtest_form(request: Request):
    """Retorna o formulário de backtest (HTML) para o HTMX carregar."""
    return templates.TemplateResponse(
        request=request,
        name="_backtest.html",
        context={"result": None, "error": None},
    )


#+------------------------------------------------------------------+
#| Helper de erro                                                   |
#+------------------------------------------------------------------+
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