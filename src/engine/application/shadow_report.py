"""Relatório de comparação sombra (F4).

Compara trades do EA v4.60 com trades do motor Python, no mesmo
símbolo/timeframe, e resume:
  - matched: trades em que ambos concordaram
  - ea_only: trades que o EA fez e o Python não
  - py_only: trades que o Python fez e o EA não
  - divergences: detalhes (bar_time, is_buy, preço, motivo)

Tudo frozen e serializável (dataclasses + `to_dict()`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from engine.infrastructure.mt5.gateway import DealInfo


@dataclass(frozen=True, slots=True)
class Divergence:
    """Uma divergência entre EA e Python em um trade.

    kind:
      - "ea_only":    o EA fez, o Python não
      - "py_only":    o Python fez, o EA não
      - "mismatch":   ambos fizeram, mas com direção/preço diferentes
    """
    kind: str
    bar_time: datetime
    is_buy: bool
    ea_deal: DealInfo | None = None
    py_price: float | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ShadowReport:
    """Resumo completo de uma janela de comparação."""
    start: datetime
    end: datetime
    matched: int = 0
    ea_only: int = 0
    py_only: int = 0
    mismatches: int = 0
    divergences: tuple[Divergence, ...] = field(default_factory=tuple)

    @property
    def total_ea(self) -> int:
        return self.matched + self.ea_only + self.mismatches

    @property
    def total_py(self) -> int:
        return self.matched + self.py_only + self.mismatches

    @property
    def match_rate(self) -> float:
        """Taxa de match: matched / max(total_ea, total_py). 1.0 = perfeito."""
        total = max(self.total_ea, self.total_py)
        if total == 0:
            return 1.0
        return self.matched / total

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "matched": self.matched,
            "ea_only": self.ea_only,
            "py_only": self.py_only,
            "mismatches": self.mismatches,
            "total_ea": self.total_ea,
            "total_py": self.total_py,
            "match_rate": self.match_rate,
            "divergences": [
                {
                    "kind": d.kind,
                    "bar_time": d.bar_time.isoformat(),
                    "is_buy": d.is_buy,
                    "ea_ticket": d.ea_deal.ticket if d.ea_deal else None,
                    "ea_price": d.ea_deal.price if d.ea_deal else None,
                    "py_price": d.py_price,
                    "detail": d.detail,
                }
                for d in self.divergences
            ],
        }