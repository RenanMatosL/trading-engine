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
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.processors.add_log_level,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
