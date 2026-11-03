"""Golden tests do StrategyConfig e StrategyRegistry (F5f)."""
from __future__ import annotations

from datetime import time

import pytest

from engine.application.registry import StrategyRegistry
from engine.config.presets import (
    DetectorParams,
    SessionParams,
    StdDevV510Preset,
    TimeWindowParams,
)
from engine.domain.strategy.strategy import StrategyConfig


def _preset(name: str = "test") -> StdDevV510Preset:
    return StdDevV510Preset.model_validate({
        "name": name, "strategy": "stddev_v510",
        "detector": DetectorParams(mute_open_min=0).model_dump(),
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=time(9, 0), end=time(17, 30)),
        ).model_dump(),
    })


def _config(name: str = "stddev_v510", magic: int = 0) -> StrategyConfig:
    return StrategyConfig(name=name, preset=_preset(name), magic=magic)


#+------------------------------------------------------------------+
#| StrategyConfig                                                   |
#+------------------------------------------------------------------+
def test_strategy_config_valido():
    cfg = _config()
    assert cfg.name == "stddev_v510"
    assert cfg.magic == 0
    assert cfg.preset.name == "stddev_v510"


def test_strategy_config_nome_vazio_rejeitado():
    with pytest.raises(ValueError, match="name"):
        StrategyConfig(name="", preset=_preset(), magic=0)
    with pytest.raises(ValueError, match="name"):
        StrategyConfig(name="   ", preset=_preset(), magic=0)


def test_strategy_config_magic_negativo_rejeitado():
    with pytest.raises(ValueError, match="magic"):
        StrategyConfig(name="x", preset=_preset("x"), magic=-1)


#+------------------------------------------------------------------+
#| StrategyRegistry                                                 |
#+------------------------------------------------------------------+
def test_registry_registrar_e_listar():
    reg = StrategyRegistry()
    reg.register(_config("a", magic=1))
    reg.register(_config("b", magic=2))
    assert reg.list() == ["a", "b"]
    assert "a" in reg
    assert "b" in reg
    assert "c" not in reg


def test_registry_nome_duplicado_falha():
    reg = StrategyRegistry()
    reg.register(_config("a", magic=1))
    with pytest.raises(ValueError, match="já registrada"):
        reg.register(_config("a", magic=2))


def test_registry_magic_duplicado_falha():
    reg = StrategyRegistry()
    reg.register(_config("a", magic=1))
    with pytest.raises(ValueError, match="magic"):
        reg.register(_config("b", magic=1))


def test_registry_get_e_resolve():
    reg = StrategyRegistry()
    reg.register(_config("a", magic=1))
    reg.register(_config("b", magic=2))
    assert reg.get("a").name == "a"
    assert [c.name for c in reg.resolve(["a", "b"])] == ["a", "b"]
    # resolve sem nomes retorna todas
    assert [c.name for c in reg.resolve()] == ["a", "b"]


def test_registry_nome_inexistente_falha():
    reg = StrategyRegistry()
    with pytest.raises(KeyError, match="não registrada"):
        reg.get("x")
    reg.register(_config("a", magic=1))
    with pytest.raises(KeyError, match="não registrada"):
        reg.resolve(["a", "x"])


def test_registry_clear():
    reg = StrategyRegistry()
    reg.register(_config("a", magic=1))
    reg.clear()
    assert reg.list() == []
    assert len(reg) == 0
    # Pode registrar de novo após clear
    reg.register(_config("a", magic=1))
    assert len(reg) == 1