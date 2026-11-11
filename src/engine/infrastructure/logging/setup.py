"""Diario estruturado (structlog): legivel no console, JSON quando auditoria pedir."""
from __future__ import annotations

import logging

import structlog


def setup_logging(json_output: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,  # 1º: Adiciona o [info]
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),  # 2º: Adiciona o horário LOCAL
            renderer,  # 3º: Imprime na tela
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        # cache_logger_on_first_use=True, (opcional, mas recomendado para performance)
    )
