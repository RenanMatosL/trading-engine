"""StateStore in-memory — testes e desenvolvimento.

Estado vive só na memória do processo. Reiniciar = perde tudo.
Útil para testes que não querem tocar em disco.
"""
from __future__ import annotations

import copy

from engine.domain.state.store import SessionSnapshot, StateStore
from engine.domain.strategy.location import RegionState


class InMemoryStateStore:
    """Implementação simples de `StateStore` sem persistência real."""

    def __init__(self) -> None:
        self._snapshot: SessionSnapshot | None = None
        self._regions: list[RegionState] = []

    def save_session(self, snapshot: SessionSnapshot) -> None:
        self._snapshot = snapshot

    def load_session(self) -> SessionSnapshot | None:
        return self._snapshot

    def save_regions(self, regions: list[RegionState]) -> None:
        # Deep copy para isolar o store do caller (testes mais determinísticos)
        self._regions = [copy.deepcopy(r) for r in regions]

    def load_regions(self) -> list[RegionState]:
        return [copy.deepcopy(r) for r in self._regions]

    def clear(self) -> None:
        self._snapshot = None
        self._regions = []