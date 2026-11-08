"""Endpoint /metrics (F12) — formato Prometheus."""
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from engine.application.metrics_exporter import get_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Retorna as métricas no formato Prometheus (text/plain)."""
    return get_metrics()