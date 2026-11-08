"""Endpoints `/api/preset` (F7c).

- GET  /api/preset  → retorna o preset YAML como JSON (ou HTML com form)
- POST /api/preset  → valida e salva o preset YAML

Validação: pydantic (`StdDevV510Preset.model_validate`). Se inválido,
retorna 400 com a mensagem do pydantic.

Backup: antes de salvar, copia o YAML atual para `.bak` (F7c).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import structlog
import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from engine.config.presets import (
    StdDevV510Preset,
    load_preset,
)
from engine.config.settings import EngineSettings


log = structlog.get_logger()

router = APIRouter(prefix="/api/preset", tags=["preset"])

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _get_preset_path(request: Request) -> Path:
    """Retorna o caminho do preset (usa app.state.preset_path se existir)."""
    preset_path = getattr(request.app.state, "preset_path", None)
    if preset_path is None:
        settings = request.app.state.settings
        return Path(settings.preset).resolve()
    return Path(preset_path)


def _serialize(preset: StdDevV510Preset) -> dict:
    """Serializa o preset para JSON (dict)."""
    return preset.model_dump(mode="json")


@router.get("")
async def get_preset(request: Request):
    """Retorna o preset atual (JSON ou HTML com formulário)."""
    preset_path = _get_preset_path(request)
    try:
        preset = load_preset(preset_path)
    except Exception as exc:  # noqa: BLE001
        log.error("preset_load_falhou", path=str(preset_path), erro=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Falha ao carregar preset: {exc}"},
        )

    is_htmx = request.headers.get("hx-request") == "true"
    if is_htmx:
        return templates.TemplateResponse(
            request=request,
            name="_preset.html",
            context={
                "preset": _serialize(preset),
                "saved": False,
                "error": None,
            },
        )

    return _serialize(preset)


@router.post("")
async def save_preset(request: Request):
    """Recebe JSON, valida com pydantic, faz backup e salva o YAML."""
    preset_path = _get_preset_path(request)
    is_htmx = request.headers.get("hx-request") == "true"

    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        msg = f"JSON inválido: {exc}"
        if is_htmx:
            return templates.TemplateResponse(
                request=request,
                name="_preset.html",
                context={"preset": {}, "saved": False, "error": msg},
                status_code=400,
            )
        return JSONResponse(status_code=400, content={"error": msg})

    # 1. Valida com pydantic
    try:
        preset = StdDevV510Preset.model_validate(body)
    except ValidationError as exc:
        msg = exc.errors()[0]["msg"] if exc.errors() else "preset inválido"
        log.warning("preset_invalido", erro=msg)
        if is_htmx:
            return templates.TemplateResponse(
                request=request,
                name="_preset.html",
                context={"preset": body, "saved": False, "error": msg},
                status_code=400,
            )
        return JSONResponse(status_code=400, content={"error": msg})

    # 2. Backup (F7c)
    try:
        if preset_path.exists():
            backup = preset_path.with_suffix(preset_path.suffix + ".bak")
            shutil.copy2(preset_path, backup)
            log.info("preset_backup", path=str(backup))
    except Exception as exc:  # noqa: BLE001
        log.warning("preset_backup_falhou", erro=str(exc))

    # 3. Salva o YAML
    try:
        preset_path.parent.mkdir(parents=True, exist_ok=True)
        preset_path.write_text(
            yaml.safe_dump(
                preset.model_dump(mode="json"),
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        log.info("preset_saved", path=str(preset_path))
    except Exception as exc:  # noqa: BLE001
        msg = f"Falha ao salvar YAML: {exc}"
        log.error("preset_save_falhou", erro=str(exc))
        if is_htmx:
            return templates.TemplateResponse(
                request=request,
                name="_preset.html",
                context={"preset": body, "saved": False, "error": msg},
                status_code=500,
            )
        return JSONResponse(status_code=500, content={"error": msg})

    # 4. Sucesso
    if is_htmx:
        return templates.TemplateResponse(
            request=request,
            name="_preset.html",
            context={
                "preset": _serialize(preset),
                "saved": True,
                "error": None,
            },
        )
    return {"ok": True, "preset": _serialize(preset)}