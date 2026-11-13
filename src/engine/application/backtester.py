"""Backtester próprio (F6).

Consome `list[Bar]` (do `csv_loader`) e retorna `BacktestResult` com
`SimulationResult` (trades + equity + stats) + métricas (sharpe, drawdown, etc).

Aproximação de ticks: como o CSV só tem candles, o `Backtester` gera
2 ticks por candle (open e close). Isso é conservador — o candle real pode
tocar SL/TP em qualquer ponto, mas o simulador só vê os extremos.

Reusa `EventFeed` (F2d) + `SimulatedExecutor` (F2d + F5e) +
`VolumeStdDetector` (F1). Não duplica lógica.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import structlog

from engine.application.events import BarEvent, EventFeed, TickEvent
from engine.application.metrics import (
    average_win_loss,
    max_drawdown,
    profit_factor,
    sharpe,
    total_return,
    win_rate,
)
from engine.application.simulation import (
    SimulationResult,
    SimulatedExecutor,
    run_simulation,
)
from engine.application.trading_session import TradingSession
from engine.config.presets import StdDevV510Preset
from engine.domain.shared.types import Bar, MarketSnapshot
from engine.domain.strategy.detector import VolumeStdDetector


log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Resultado de um backtest."""
    simulation: SimulationResult
    metrics: dict[str, float]
    start: datetime
    end: datetime
    n_bars: int


class Backtester:
    """Roda backtest sobre uma lista de `Bar`."""

    def __init__(
        self,
        preset: StdDevV510Preset,
        *,
        initial_balance: float = 100_000.0,
        slippage_points: float = 0.0,
        spread_points: float = 0.0,
    ) -> None:
        self._preset = preset
        self._initial_balance = initial_balance
        self._slippage = slippage_points
        self._spread = spread_points

    def run(self, bars: list[Bar]) -> BacktestResult:
        """Roda backtest sobre `bars` (lista de candles fechados, ordem cronológica)."""
        if not bars:
            raise ValueError("bars está vazia")

        start = bars[0].time
        end = bars[-1].time

        feed = self._build_feed(bars)

        session = TradingSession(self._preset, is_backtest=True)  # F16
        
        simulation = run_simulation(
            feed, self._preset, session=session,
            initial_balance=self._initial_balance,
            slippage_points=self._slippage,
            spread_points=self._spread,
        )

        metrics = self._compute_metrics(simulation, self._initial_balance)

        log.info(
            "backtest_done",
            n_bars=len(bars),
            n_trades=len(simulation.trades),
            final_balance=round(simulation.stats.get("final_balance", 0.0), 2),
            return_pct=round(simulation.stats.get("return_pct", 0.0), 2),
        )

        return BacktestResult(
            simulation=simulation,
            metrics=metrics,
            start=start,
            end=end,
            n_bars=len(bars),
        )

    # ----------------------------------------------------------------
    def _build_feed(self, bars: list[Bar]) -> EventFeed:
        """Constrói `EventFeed` a partir de `bars`.

        Para cada candle:
          - 1 `BarEvent(bar, zscore)` (z-score calculado incrementalmente).
          - 2 `TickEvent` (open e close) — aproximação de ticks.

        `EventFeed` exige ordem cronológica estrita. Os ticks `open`/`close`
        do mesmo candle são adicionados **junto** com o candle (para manter
        a ordem). O `EventFeed` aceita ticks com o mesmo timestamp do candle.
        """
        det = VolumeStdDetector(
            length=self._preset.detector.length,
            std_ref=self._preset.detector.std_ref,
            source=self._preset.detector.volume_source,
        )

        events: list = []
        for bar in bars:
            reading = det.on_bar_closed(bar)
            # O z-score só existe a partir do LENGTH-esimo candle.
            # Antes disso, usa zscore=0 (o Backtester não vai gerar região).
            zscore = reading.zscore if reading is not None else 0.0

            events.append(BarEvent(bar=bar, zscore=zscore))
            events.append(TickEvent(_snap(bar.open, bar.open, bar.time)))
            events.append(TickEvent(_snap(bar.close, bar.close, bar.time)))

        return EventFeed(events)

    # ----------------------------------------------------------------
    def _compute_metrics(
        self,
        simulation: SimulationResult,
        initial_balance: float,
    ) -> dict[str, float]:
        """Calcula métricas a partir do `SimulationResult`."""
        trades = simulation.trades
        equity = simulation.equity_curve

        aw, al = average_win_loss(trades)
        return {
            "sharpe": sharpe(trades),
            "max_drawdown_pct": max_drawdown(equity) * 100.0,
            "win_rate": win_rate(trades),
            "profit_factor": profit_factor(trades),
            "avg_win": aw,
            "avg_loss": al,
            "total_return_pct": total_return(trades, initial_balance),
        }


def _snap(ask: float, bid: float, now: datetime) -> MarketSnapshot:
    return MarketSnapshot(ask=ask, bid=bid, now=now)