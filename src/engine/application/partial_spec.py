"""Especificação de um alvo parcial (F5a).

`PartialSpec` é um dataclass frozen que descreve UM tier de saída parcial
(contratos + pontos a partir da entrada). O `target_price()` calcula o
preço-alvo dado entrada + direção.

Espelha `InpPartial*Points` / `InpPartial*Contracts` do EA v4.60.

Não acessa MT5. Não coloca ordem. Só descreve o que o Executor deve fazer.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.config.presets import PartialExitType


@dataclass(frozen=True, slots=True)
class PartialSpec:
    """Um tier de saída parcial.

    `tier_index`: 0, 1, 2 (Tier 1, 2, 3 do EA).
    `contracts`: quantos contratos sair neste tier.
    `points`: alvo em pontos a partir da entrada.
    `percent`: alvo em % do preço de entrada (se `exit_type=percent`).
    """
    tier_index: int
    contracts: int
    points: float
    percent: float = 0.0

    def __post_init__(self) -> None:
        if self.tier_index < 0:
            raise ValueError("tier_index deve ser >= 0")
        if self.contracts < 0:
            raise ValueError("contracts deve ser >= 0")
        if self.points < 0:
            raise ValueError("points deve ser >= 0")
        if self.percent < 0:
            raise ValueError("percent deve ser >= 0")

    @property
    def enabled(self) -> bool:
        return self.contracts > 0

    def target_price(
        self,
        entry_price: float,
        is_buy: bool,
        exit_type: PartialExitType,
    ) -> float:
        """Preço-alvo do tier.

        `exit_type=POINTS`: entry ± points
        `exit_type=PERCENT`: entry ± (entry * percent / 100)
        """
        if exit_type == PartialExitType.PERCENT:
            distance = entry_price * self.percent / 100.0
        else:
            distance = self.points
        return entry_price + distance if is_buy else entry_price - distance


def make_partial_specs(
    *,
    use_partial_exit: bool,
    tiers: list,  # list[PartialTier] do preset (evita import circular)
    exit_type: PartialExitType,
    partial_points: float,
    partial_percent: float,
) -> tuple[PartialSpec, ...] | None:
    """Constrói a tupla de `PartialSpec` a partir do preset.

    Retorna `None` se `use_partial_exit=False`.

    Regras (espelham o EA):
      - Tier 1 usa `partial_points`/`partial_percent` (global).
      - Tier 2 e 3 usam seus próprios `points` (não têm percent).
      - Tiers com `contracts=0` são pulados.
    """
    if not use_partial_exit:
        return None

    out: list[PartialSpec] = []
    for i, tier in enumerate(tiers):
        if tier.contracts <= 0:
            continue
        if i == 0:
            # Tier 1 usa o global (points/percent); o `tier.points` é ignorado
            # quando o modo é percent.
            out.append(PartialSpec(
                tier_index=0,
                contracts=tier.contracts,
                points=partial_points,
                percent=partial_percent,
            ))
        else:
            out.append(PartialSpec(
                tier_index=i,
                contracts=tier.contracts,
                points=tier.points,
                percent=0.0,  # tier 2/3 não têm percent no EA
            ))
    return tuple(out) if out else None