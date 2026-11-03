"""Janela operacional (hora do SERVIDOR da corretora) - espelho do filtro do EA."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time


@dataclass(frozen=True, slots=True)
class TradingWindow:
    start: time
    end: time

    def is_open(self, now: datetime) -> bool:
        cur = now.time()
        if self.start == self.end:
            return True
        if self.start < self.end:
            return self.start <= cur < self.end
        return cur >= self.start or cur < self.end   # janela cruzando meia-noite

    def session_shift(
        self,
        bar_time,
        now,
        calendar,
    ) -> int:
        """Número de pregões entre `bar_time` e `now` (F5d).

        Conta **dias úteis sem feriados** (calendário B3), não dias corridos.
        `0` = mesmo dia; `1` = pregão anterior; etc.

        Se `bar_time > now`, retorna negativo (evento futuro).

        Args:
            bar_time: datetime da região (fuso do servidor).
            now: datetime atual (fuso do servidor).
            calendar: B3Calendar (lista de feriados).
        """
        if calendar is None:
            # Fallback: dias corridos (comportamento antigo)
            return (now.date() - bar_time.date()).days
        return calendar.trading_days_between(bar_time.date(), now.date())
    
