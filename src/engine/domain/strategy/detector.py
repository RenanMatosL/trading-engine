"""Detector de candle-sinal por z-score de volume.

Semantica IDENTICA ao EA v5.10 / VolumeStdBarPainter:
- janela = ultimos `length` candles FECHADOS, INCLUINDO o candle avaliado;
- media aritmetica; desvio padrao amostral (n-1);
- sinal quando z >= std_ref.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from engine.domain.shared.types import Bar, VolumeSource


@dataclass(frozen=True, slots=True)
class DetectorReading:
    zscore: float
    mean: float
    std: float
    volume: float
    is_signal: bool


class VolumeStdDetector:
    """Janela rolante O(1) por barra (somas incrementais)."""

    def __init__(self, length: int, std_ref: float, source: VolumeSource) -> None:
        if length < 2:
            raise ValueError("length deve ser >= 2")
        if std_ref <= 0:
            raise ValueError("std_ref deve ser > 0")
        self._length = length
        self._std_ref = std_ref
        self._source = source
        self._win: deque[float] = deque(maxlen=length)
        self._sum = 0.0
        self._sumsq = 0.0

    @property
    def ready(self) -> bool:
        return len(self._win) == self._length

    def on_bar_closed(self, bar: Bar) -> DetectorReading | None:
        """Alimenta o candle fechado; retorna a leitura quando a janela completa."""
        v = bar.volume(self._source)
        if len(self._win) == self._length:          # janela cheia: sai o mais antigo
            old = self._win[0]
            self._sum -= old
            self._sumsq -= old * old
        self._win.append(v)
        self._sum += v
        self._sumsq += v * v

        if not self.ready:
            return None

        n = float(self._length)
        mean = self._sum / n
        var = (self._sumsq - self._sum * mean) / (n - 1.0)
        std = math.sqrt(var) if var > 0.0 else 0.0
        z = (v - mean) / std if std > 0.0 else 0.0
        return DetectorReading(
            zscore=z, mean=mean, std=std, volume=v, is_signal=z >= self._std_ref
        )
