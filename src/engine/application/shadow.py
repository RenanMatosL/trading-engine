"""ShadowComparer — compara trades do EA com trades do Python (F4).

Algoritmo:
  1. Constrói chave `(bar_time, is_buy)` para cada trade (EA e Python).
  2. Para cada chave presente nos dois, verifica se preço bate (±tolerância).
     - bate → matched
     - não bate → mismatch
  3. Chaves só no EA → ea_only.
  4. Chaves só no Python → py_only.

Não acessa MT5. Roda com dados que o caller já coletou.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from engine.application.intent import TradeIntent
from engine.application.shadow_report import Divergence, ShadowReport
from engine.infrastructure.mt5.gateway import DealInfo


DEFAULT_TOLERANCE_POINTS = 2.0


def _key_e(deal: DealInfo) -> tuple[datetime, bool]:
    return (deal.time, deal.is_buy)


def _key_py(trade: TradeIntent) -> tuple[datetime, bool]:
    return (trade.bar_time, trade.is_buy)


def _matches_price(
    ea_deal: DealInfo, py_trade: TradeIntent, tolerance: float
) -> bool:
    return abs(ea_deal.price - py_trade.entry_price) <= tolerance


class ShadowComparer:
    """Compara trades do EA com trades do Python, chave por (bar_time, is_buy)."""

    def compare(
        self,
        ea_deals: list[DealInfo],
        py_trades: list[TradeIntent],
        *,
        start: datetime,
        end: datetime,
        tolerance_points: float = DEFAULT_TOLERANCE_POINTS,
    ) -> ShadowReport:
        """Retorna o relatório de match/divergência.

        `ea_deals` devem ser de ENTRADA (is_entry=True). Se vierem saídas,
        filtra automaticamente.
        """
        ea_entries = [d for d in ea_deals if d.is_entry]
        py_list = list(py_trades)

        ea_by_key: dict[tuple[datetime, bool], list[DealInfo]] = defaultdict(list)
        for d in ea_entries:
            ea_by_key[_key_e(d)].append(d)

        py_by_key: dict[tuple[datetime, bool], list[TradeIntent]] = defaultdict(list)
        for t in py_list:
            py_by_key[_key_py(t)].append(t)

        matched = 0
        ea_only = 0
        py_only = 0
        mismatches = 0
        divergences: list[Divergence] = []

        all_keys = set(ea_by_key.keys()) | set(py_by_key.keys())
        for key in all_keys:
            bar_time, is_buy = key
            ea_list = ea_by_key.get(key, [])
            py_list_k = py_by_key.get(key, [])

            # Emparelha por ordem (mais simples: 1 EA ↔ 1 Python)
            n_pairs = min(len(ea_list), len(py_list_k))
            for i in range(n_pairs):
                ea_d = ea_list[i]
                py_t = py_list_k[i]
                if _matches_price(ea_d, py_t, tolerance_points):
                    matched += 1
                else:
                    mismatches += 1
                    divergences.append(Divergence(
                        kind="mismatch",
                        bar_time=bar_time,
                        is_buy=is_buy,
                        ea_deal=ea_d,
                        py_price=py_t.entry_price,
                        detail=(
                            f"preço: EA={ea_d.price:.2f} "
                            f"Python={py_t.entry_price:.2f} "
                            f"(tol={tolerance_points:.2f})"
                        ),
                    ))

            # Sobras do EA
            for ea_d in ea_list[n_pairs:]:
                ea_only += 1
                divergences.append(Divergence(
                    kind="ea_only",
                    bar_time=bar_time,
                    is_buy=is_buy,
                    ea_deal=ea_d,
                    detail=f"EA fez trade (price={ea_d.price:.2f}), Python não",
                ))

            # Sobras do Python
            for py_t in py_list_k[n_pairs:]:
                py_only += 1
                divergences.append(Divergence(
                    kind="py_only",
                    bar_time=bar_time,
                    is_buy=is_buy,
                    py_price=py_t.entry_price,
                    detail=f"Python fez trade (price={py_t.entry_price:.2f}), EA não",
                ))

        return ShadowReport(
            start=start,
            end=end,
            matched=matched,
            ea_only=ea_only,
            py_only=py_only,
            mismatches=mismatches,
            divergences=tuple(divergences),
        )