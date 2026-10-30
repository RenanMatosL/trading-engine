"""Configuracao de ambiente (credenciais/terminal) via pydantic-settings + .env."""
from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MT5Settings(BaseModel):
    login: int = 0
    password: str = ""
    server: str = ""
    symbol: str = "WIN$N"
    terminal_path: str = ""            # vazio = terminal padrao instalado


class EngineSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ENGINE_", env_nested_delimiter="__",
        env_file=".env", env_file_encoding="utf-8", extra="ignore",
    )
    mt5: MT5Settings = Field(default_factory=MT5Settings)
    preset: str = "presets/stddev_v510_default.yaml"
    log_json: bool = False             # False = legivel no console; True = JSON p/ auditoria
