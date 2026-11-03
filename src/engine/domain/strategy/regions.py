"""RegionManager — gerencia o ciclo de vida das regiões de trade-location.

Porta o comportamento do EA v4.60 SEM filtros de sessão (que ficam no
TradingSession). Aqui só:
  - registrar regiões quando z >= std_ref (chamado externamente);
  - atualizar rompimentos dados os preços correntes;
  - aplicar validade por pregões e TTL pós-rompimento;
  - governança (região de maior volume ou primeira a romper);
  - consumir/rearmar.

Sem dependência de MT5, de relógio global, ou de ordens. Testável com
pytest puro usando `MarketSnapshot` e listas de candles.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from enum import Enum
from typing import Callable

from engine.domain.shared.types import MarketSnapshot
from engine.domain.strategy.location import (
    RegisterResult,
    RegionPhase,
    RegionState,
    TradeLocation,
)
from engine.domain.risk.calendar import TradingWindow
from engine.domain.risk.exchange_calendar import B3Calendar


# Parâmetros do EA v4.60 (default) que afetam o gerenciador de regiões.
DEFAULT_MAX_LOC = 12
DEFAULT_VALID_DAYS = 2
DEFAULT_BREAKOUT_TTL_MIN = 60

# Assinaturas dos callbacks de SL/TP.
StopLevelFn = Callable[[TradeLocation, bool], float]
TakeProfitFn = Callable[[TradeLocation, bool], float]


class CandidateMode(str, Enum):
    """Como escolher a região governante quando várias estão BROKEN."""
    HIGHEST_VOLUME = "highest_volume"
    FIRST_READY = "first_ready"


class RegionManager:
    """Gerencia o dict[bar_time, RegionState].

    Threading: NÃO é thread-safe. Um manager por estratégia/par símbolo.
    """

    def __init__(
        self,
        *,
        max_loc: int = DEFAULT_MAX_LOC,
        valid_days: int = DEFAULT_VALID_DAYS,
        breakout_ttl_min: int = DEFAULT_BREAKOUT_TTL_MIN,
        candidate_mode: CandidateMode = CandidateMode.HIGHEST_VOLUME,
        calendar: B3Calendar | None = None,
    ) -> None:
        if max_loc < 1:
            raise ValueError("max_loc deve ser >= 1")
        if valid_days < 0:
            raise ValueError("valid_days deve ser >= 0")
        if breakout_ttl_min < 0:
            raise ValueError("breakout_ttl_min deve ser >= 0")
        self._max_loc = max_loc
        self._valid_days = valid_days
        self._ttl = timedelta(minutes=breakout_ttl_min)
        self._candidate_mode = candidate_mode
        self._calendar = calendar
        self._regions: dict[datetime, RegionState] = {}

    # ----------------------------------------------------------------
    # Consultas
    # ----------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._regions)

    def get(self, bar_time: datetime) -> RegionState | None:
        return self._regions.get(bar_time)

    def all(self) -> list[RegionState]:
        return list(self._regions.values())

    # ----------------------------------------------------------------
    # Registro
    # ----------------------------------------------------------------
    def register(
        self,
        *,
        bar_time: datetime,
        high: float,
        low: float,
        volume: float,
        big_candle: bool,
        now: datetime,
    ) -> tuple[RegisterResult, RegionState | None]:
        """Registra uma nova região (3 cenários: há espaço / recicla / compara volume)."""
        if bar_time in self._regions:
            return RegisterResult.SKIPPED_DUPLICATE, None

        location = TradeLocation(
            bar_time=bar_time, high=high, low=low,
            volume=volume, big_candle=big_candle,
        )

        if len(self._regions) < self._max_loc:
            state = RegionState(location=location)
            self._regions[bar_time] = state
            return RegisterResult.CREATED, state

        recyclable = self._find_recyclable(now)
        if recyclable is not None:
            self._regions.pop(recyclable)
            state = RegionState(location=location)
            self._regions[bar_time] = state
            return RegisterResult.REPLACED_LOWEST, state

        worst_key = min(self._regions, key=lambda k: self._regions[k].volume)
        if volume <= self._regions[worst_key].volume:
            return RegisterResult.SKIPPED_FULL_QUEUE, None

        self._regions.pop(worst_key)
        state = RegionState(location=location)
        self._regions[bar_time] = state
        return RegisterResult.REPLACED_LOWEST, state

    def _find_recyclable(self, now: datetime) -> datetime | None:
        for key, state in self._regions.items():
            if state.phase == RegionPhase.CONSUMED:
                return key
            if not self._is_within_validity(state, now):
                return key
        return None

    # ----------------------------------------------------------------
    # Rompimento
    # ----------------------------------------------------------------
    def update_breakouts(
        self,
        snapshot: MarketSnapshot,
        *,
        stop_level_fn: StopLevelFn,
        take_profit_fn: TakeProfitFn,
    ) -> list[RegionState]:
        """Atualiza rompimentos. Retorna as regiões que viraram BROKEN neste tick."""
        just_broke: list[RegionState] = []
        for state in self._regions.values():
            if state.phase not in (RegionPhase.WAITING_BREAKOUT, RegionPhase.REARMED):
                continue
            loc = state.location
            if snapshot.ask > loc.high:
                is_buy = True
            elif snapshot.bid < loc.low:
                is_buy = False
            else:
                continue
            state.is_buy = is_buy
            state.stop_loss = stop_level_fn(loc, is_buy)
            state.take_profit = take_profit_fn(loc, is_buy)
            state.broken_time = snapshot.now
            state.phase = RegionPhase.BROKEN
            just_broke.append(state)
        return just_broke

    # ----------------------------------------------------------------
    # Expiração e validade
    # ----------------------------------------------------------------
    def sweep_expired(self, now: datetime) -> list[RegionState]:
        expired: list[RegionState] = []
        for state in list(self._regions.values()):
            if not state.is_alive:
                continue
            if state.phase == RegionPhase.BROKEN and state.broken_time is not None:
                if self._ttl.total_seconds() > 0 and \
                   now > state.broken_time + self._ttl:
                    state.phase = RegionPhase.CONSUMED
                    expired.append(state)
                    continue
            if not self._is_within_validity(state, now):
                state.phase = RegionPhase.CONSUMED
                expired.append(state)
        return expired

    def _is_within_validity(self, state: RegionState, now: datetime) -> bool:
        """Validade da região por `valid_days` pregões.

        - Com `B3Calendar` (F5d): conta **pregões reais** (dias úteis
          sem feriados), via `TradingWindow.session_shift`.
        - Sem `B3Calendar`: fallback para **dias corridos** (comportamento
          antigo, para testes que não injetam calendar).
        """
        if self._calendar is not None:
            shift = TradingWindow(
                start=time(0, 0), end=time(0, 0),  # irrelevante p/ session_shift
            ).session_shift(
                bar_time=state.bar_time,
                now=now,
                calendar=self._calendar,
            )
            return shift <= self._valid_days

        # Fallback: dias corridos (comportamento antigo)
        delta_days = (now.date() - state.bar_time.date()).days
        return delta_days <= self._valid_days

    # ----------------------------------------------------------------
    # Governança
    # ----------------------------------------------------------------
    def governing(self) -> RegionState | None:
        candidates = [s for s in self._regions.values() if s.can_be_candidate]
        if not candidates:
            return None
        if self._candidate_mode == CandidateMode.FIRST_READY:
            return min(candidates, key=lambda s: (s.broken_time, s.bar_time))
        return min(candidates, key=lambda s: (-s.volume, s.bar_time))

    # ----------------------------------------------------------------
    # Transições terminais
    # ----------------------------------------------------------------
    def consume(self, bar_time: datetime) -> RegionState | None:
        state = self._regions.get(bar_time)
        if state is None:
            return None
        state.phase = RegionPhase.CONSUMED
        return state

    def rearm_after_sl(
        self,
        bar_time: datetime,
        *,
        allow_unlimited: bool,
    ) -> RegionState | None:
        state = self._regions.get(bar_time)
        if state is None:
            return None
        if not allow_unlimited and state.rearmed_once:
            state.phase = RegionPhase.CONSUMED
            return state
        state.phase = RegionPhase.REARMED
        state.is_buy = False
        state.stop_loss = 0.0
        state.take_profit = 0.0
        state.broken_time = None
        state.rearmed_once = True
        return state

    def clear(self) -> None:
        self._regions.clear()