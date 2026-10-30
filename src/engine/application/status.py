"""Caso de uso F0/F1: status do motor - conta, simbolo, ultimo candle e leitura do detector."""
from __future__ import annotations

from dataclasses import dataclass

from engine.config.presets import StdDevV510Preset
from engine.domain.strategy.detector import DetectorReading, VolumeStdDetector
from engine.infrastructure.mt5.gateway import AccountInfo, BrokerGateway


@dataclass(frozen=True, slots=True)
class EngineStatus:
    account: AccountInfo
    symbol: str
    bars_loaded: int
    last_bar_time: str
    last_close: float
    reading: DetectorReading | None


def get_status(gw: BrokerGateway, symbol: str, preset: StdDevV510Preset) -> EngineStatus:
    det = VolumeStdDetector(
        length=preset.detector.length,
        std_ref=preset.detector.std_ref,
        source=preset.detector.volume_source,
    )
    bars = gw.closed_bars(symbol, preset.detector.timeframe, preset.detector.length)
    reading: DetectorReading | None = None
    for bar in bars:
        reading = det.on_bar_closed(bar)
    last = bars[-1] if bars else None
    return EngineStatus(
        account=gw.account(),
        symbol=symbol,
        bars_loaded=len(bars),
        last_bar_time=last.time.strftime("%Y-%m-%d %H:%M") if last else "-",
        last_close=last.close if last else 0.0,
        reading=reading,
    )
