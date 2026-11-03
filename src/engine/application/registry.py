"""Registry de estratégias (F5f).

Guarda `StrategyConfig` por nome. O `engine run --strategies=A,B` usa
para resolver os nomes para configs concretas.

Não acessa MT5. Não cria sessões. Só guarda e devolve configs.
"""
from __future__ import annotations

import structlog

from engine.domain.strategy.strategy import StrategyConfig


log = structlog.get_logger()


class StrategyRegistry:
    """Registry de estratégias por nome.

    Uso:
        reg = StrategyRegistry()
        reg.register(StrategyConfig(name="stddev_v510", preset=..., magic=0))
        reg.register(StrategyConfig(name="outra", preset=..., magic=1))
        configs = reg.resolve(["stddev_v510", "outra"])
    """

    def __init__(self) -> None:
        self._by_name: dict[str, StrategyConfig] = {}
        self._used_magics: set[int] = set()

    def register(self, config: StrategyConfig) -> None:
        """Registra uma estratégia. Falha se o nome ou o magic já existe."""
        if config.name in self._by_name:
            raise ValueError(f"estratégia '{config.name}' já registrada")
        if config.magic in self._used_magics:
            raise ValueError(
                f"magic {config.magic} já usado por outra estratégia "
                f"(precisa ser único)"
            )
        self._by_name[config.name] = config
        self._used_magics.add(config.magic)
        log.info(
            "strategy_registered",
            name=config.name, magic=config.magic,
        )

    def get(self, name: str) -> StrategyConfig:
        """Retorna a config pelo nome. Falha se não existir."""
        if name not in self._by_name:
            raise KeyError(f"estratégia '{name}' não registrada")
        return self._by_name[name]

    def list(self) -> list[str]:
        """Lista os nomes das estratégias registradas (ordem alfabética)."""
        return sorted(self._by_name.keys())

    def resolve(self, names: list[str] | None = None) -> list[StrategyConfig]:
        """Resolve uma lista de nomes para configs.

        Se `names is None` ou vazio, retorna TODAS as estratégias registradas.
        Falha se algum nome não existir.
        """
        if not names:
            return [self._by_name[n] for n in self.list()]
        return [self.get(n) for n in names]

    def clear(self) -> None:
        self._by_name.clear()
        self._used_magics.clear()

    def __len__(self) -> int:
        return len(self._by_name)

    def __contains__(self, name: str) -> bool:
        return name in self._by_name
    