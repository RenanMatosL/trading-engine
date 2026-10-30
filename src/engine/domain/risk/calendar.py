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
