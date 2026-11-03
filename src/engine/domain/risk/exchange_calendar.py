"""Calendário de pregões da B3 (F5d).

Conta **pregões** (dias úteis sem feriados), não dias corridos.
Espelha a semântica de `SessionShift(bar_time)` do EA v4.60, que usa
`iBarShift(_Symbol, PERIOD_D1, barTime)` — mas com a lista de feriados
hardcoded (B3 não tem API pública estável).

Zero dependências externas (só stdlib). Testável com pytest puro.

**TODO F5+:** atualizar a lista de feriados uma vez por ano
(Carnaval, Sexta-Santa, Corpus Christi, 7/9, 12/10, 2/11, 15/11,
25/12, 1/1, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


#+------------------------------------------------------------------+
#| Feriados B3 (2026-2027)                                          |
#| Fonte: https://www.b3.com.br/pt_br/solucoes/plataformas/       |
#|         puweb/calendario-de-negociacao/                          |
#+------------------------------------------------------------------+
FERIADOS_B3: frozenset[date] = frozenset({
    # 2026
    date(2026, 1, 1),    # Confraternização Universal
    date(2026, 2, 16),   # Carnaval (segunda)
    date(2026, 2, 17),   # Carnaval (terça)
    date(2026, 4, 3),    # Sexta-feira Santa
    date(2026, 4, 21),   # Tiradentes
    date(2026, 5, 1),    # Dia do Trabalho
    date(2026, 6, 4),    # Corpus Christi
    date(2026, 9, 7),    # Independência
    date(2026, 10, 12),  # Nossa Senhora Aparecida
    date(2026, 11, 2),   # Finados
    date(2026, 11, 15),  # Proclamação da República
    date(2026, 11, 20),  # Consciência Negra (a partir de 2024)
    date(2026, 12, 25),  # Natal
    # 2027
    date(2027, 1, 1),    # Confraternização Universal
    date(2027, 2, 8),    # Carnaval (segunda)
    date(2027, 2, 9),    # Carnaval (terça)
    date(2027, 3, 26),   # Sexta-feira Santa
    date(2027, 4, 21),   # Tiradentes
    date(2027, 5, 1),    # Dia do Trabalho
    date(2027, 5, 27),   # Corpus Christi
    date(2027, 9, 7),    # Independência
    date(2027, 10, 12),  # Nossa Senhora Aparecida
    date(2027, 11, 2),   # Finados
    date(2027, 11, 15),  # Proclamação da República
    date(2027, 11, 20),  # Consciência Negra
    date(2027, 12, 25),  # Natal
})


@dataclass(frozen=True, slots=True)
class B3Calendar:
    """Calendário de pregões da B3.

    `holidays` permite sobrescrever a lista default (útil em testes
    ou para anos além de 2027).
    """
    holidays: frozenset[date] = field(default=FERIADOS_B3)

    def is_trading_day(self, d: date) -> bool:
        """Segunda a sexta, exceto feriados."""
        if d.weekday() >= 5:  # 5=sábado, 6=domingo
            return False
        return d not in self.holidays

    def trading_days_between(self, start: date, end: date) -> int:
        """Número de pregões no intervalo [start, end].

        Se `start > end`, retorna negativo (para `session_shift`).
        Fins de semana e feriados não contam.
        """
        if start == end:
            return 0
        sign = 1
        if start > end:
            start, end = end, start
            sign = -1

        count = 0
        cur = start + timedelta(days=1)
        while cur <= end:
            if self.is_trading_day(cur):
                count += 1
            cur += timedelta(days=1)
        return sign * count