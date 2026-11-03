"""Configuração de uma estratégia (F5f).

Uma estratégia é definida por:
  - `name`: identificador único (usado no `--strategies=A,B`).
  - `preset`: o `StdDevV510Preset` com os parâmetros.
  - `magic`: o magic number (distingue as ordens no MT5).

`StrategyConfig` é frozen e serializável. O `TradingSession` usa o preset
e o magic para operar; o `engine run` usa o `name` para listar/selecionar.

Zero dependências externas (só stdlib). Testável com pytest puro.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.config.presets import StdDevV510Preset


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Configuração de uma estratégia (F5f).

    `name`: identificador único (ex: "stddev_v510").
    `preset`: o `StdDevV510Preset` (já validado pelo pydantic).
    `magic`: magic number do MT5 (distingue as ordens).
    """
    name: str
    preset: StdDevV510Preset
    magic: int = 0

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("name não pode ser vazio")
        if self.magic < 0:
            raise ValueError("magic deve ser >= 0")