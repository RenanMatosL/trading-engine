"""Dependências do FastAPI (F7a).

Fornece o `BrokerGateway` (Real ou Fake) e o `EngineSettings` via `Depends`.
O gateway é criado **uma vez** no startup (lifespan) e fechado no shutdown.

Uso:
    from fastapi import Depends
    from engine.web.deps import get_gateway, get_settings

    @app.get("/api/foo")
    async def foo(gw = Depends(get_gateway), settings = Depends(get_settings)):
        ...
"""
from __future__ import annotations

import structlog
from fastapi import Request

from engine.config.settings import EngineSettings
from engine.infrastructure.mt5.fake import FakeGateway
from engine.infrastructure.mt5.gateway import (
    BrokerGateway,
    MT5NotAvailableError,
    RealMT5Gateway,
)


log = structlog.get_logger()


def get_settings(request: Request) -> EngineSettings:
    """Retorna o `EngineSettings` (criado no lifespan)."""
    return request.app.state.settings


def get_gateway(request: Request) -> BrokerGateway | None:
    """Retorna o gateway (Real ou Fake). `None` se MT5 indisponível."""
    return getattr(request.app.state, "gateway", None)


async def startup_gateway(settings: EngineSettings) -> BrokerGateway | None:
    """Cria e conecta o gateway. Retorna `None` se MT5 indisponível.

    Chamado no lifespan do FastAPI. Se o MT5 não estiver disponível,
    loga warning e retorna `None` (o frontend mostra "MT5 indisponível").
    """
    try:
        # Se não há login configurado, usa FakeGateway (dev)
        if not settings.mt5.login:
            gw = FakeGateway()
            gw.connect()
            log.info("web_gateway_fake")
            return gw

        gw = RealMT5Gateway(settings.mt5)
        gw.connect()
        log.info("web_gateway_real", login=settings.mt5.login)
        return gw
    except MT5NotAvailableError as exc:
        log.warning("web_gateway_indisponivel", erro=str(exc))
        return None


async def shutdown_gateway(gateway: BrokerGateway | None) -> None:
    """Fecha o gateway (se existir)."""
    if gateway is not None:
        try:
            gateway.shutdown()
        except Exception:  # noqa: BLE001
            pass