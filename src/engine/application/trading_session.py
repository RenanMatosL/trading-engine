"""TradingSession — orquestrador de decisão do EA v4.60 (F2c + F3b + F3c + F5a + F5c).

F2c: on_bar_closed + on_tick (filtros de sessão + TradeIntent).
F3b: on_trade_event + rastreamento do trade atual.
F3c: save_state / _load_state / _snapshot (persistência opcional).
F5a: _make_intent preenche `partials`; on_trade_event rastreia parciais.
F5c: _maybe_arm_reentry + ReentryIntent (reforço no retorno à entrada).

Não executa ordens. Não gerencia posições. Não acessa MT5.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

import structlog

from engine.application.intent import (
    BarResult,
    ReentryIntent,
    TickDecision,
    TradeIntent,
)
from engine.application.partial_spec import make_partial_specs
from engine.application.trade_events import (
    EntryFilled,
    PartialFilled,
    PositionClosed,
    ReentryExitFilled,
    ReentryFilled,
    StopLossHit,
    TakeProfitHit,
    TradeEvent,
)
from engine.config.presets import (
    CandidateMode,
    EntryLevelMode,
    StdDevV510Preset,
)
from engine.domain.shared.types import Bar, MarketSnapshot
from engine.domain.state.store import SessionSnapshot, StateStore
from engine.domain.strategy.location import RegisterResult, RegionPhase, RegionState
from engine.domain.strategy.pricing import (
    EntryLevelMode as PricingEntryMode,
    PricingConfig,
    SLLevelMode as PricingSLMode,
    entry_level,
    is_big_candle,
    stop_level,
    take_profit_level,
)
from engine.domain.strategy.regions import (
    CandidateMode as RegionCandidateMode,
    RegionManager,
)

log = structlog.get_logger()


def _in_window(now: time, start: time, end: time) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


def _preset_to_pricing(preset: StdDevV510Preset) -> PricingConfig:
    entry = preset.entry
    stop = preset.stop
    tp = preset.take_profit
    det = preset.detector
    return PricingConfig(
        entry_mode=PricingEntryMode(entry.level_mode.value),
        entry_level_offset_points=entry.level_offset_points,
        sl_mode=PricingSLMode(stop.level_mode.value),
        sl_points=stop.sl_points,
        sl_level_offset_points=stop.level_offset_points,
        use_final_tp=tp.use_final_tp,
        final_tp_points=tp.final_tp_points,
        use_big_candle_rule=det.use_big_candle_rule,
        big_candle_min_range_points=det.big_candle_min_range,
        big_candle_entry_offset_points=det.big_candle_entry_offset,
        big_candle_sl_adjust_points=det.big_candle_sl_adjust,
        point=1.0,
    )


def _preset_to_candidate_mode(preset: StdDevV510Preset) -> RegionCandidateMode:
    if preset.regions.candidate_mode == CandidateMode.FIRST_READY:
        return RegionCandidateMode.FIRST_READY
    return RegionCandidateMode.HIGHEST_VOLUME


class TradingSession:
    """Orquestrador de decisão do EA v4.60. Threading: NÃO é thread-safe."""

    def __init__(
        self,
        preset: StdDevV510Preset,
        *,
        region_manager: RegionManager | None = None,
        pricing_config: PricingConfig | None = None,
        state_store: StateStore | None = None,
    ) -> None:
        self._preset = preset
        self._pricing = pricing_config or _preset_to_pricing(preset)

        if region_manager is None:
            region_manager = RegionManager(
                max_loc=preset.regions.max_loc,
                valid_days=preset.regions.valid_days,
                breakout_ttl_min=preset.session.breakout_ttl_min,
                candidate_mode=_preset_to_candidate_mode(preset),
            )
        self._regions = region_manager

        # Estado de sessão (espelha g_vars do EA)
        self._last_sl_time: datetime | None = None
        self._trades_today: int = 0
        self._current_day: datetime | None = None

        # F3b: rastreamento do trade atual
        self._current_entry_region: datetime | None = None
        self._current_entry_position: int | None = None
        self._current_entry_price: float | None = None      # F5c
        self._current_is_buy: bool | None = None            # F5c

        # F5a: rastreamento das parciais preenchidas
        self._partials_filled: list[int] = []

        # F5c: rastreamento do reforço
        self._reentry_armed: bool = False
        self._reentry_done: bool = False

        # Callbacks para o region_manager
        self._stop_level_fn = lambda loc, is_buy: stop_level(loc, is_buy, self._pricing)
        self._take_profit_fn = lambda loc, is_buy: take_profit_level(loc, is_buy, self._pricing)

        # F3c: persistência opcional
        self._store = state_store
        if self._store is not None:
            self._load_state()

    # ----------------------------------------------------------------
    # Propriedades (inspeção/testes)
    # ----------------------------------------------------------------
    @property
    def regions(self) -> RegionManager:
        return self._regions

    @property
    def pricing(self) -> PricingConfig:
        return self._pricing

    @property
    def trades_today(self) -> int:
        return self._trades_today

    @property
    def last_sl_time(self) -> datetime | None:
        return self._last_sl_time

    @property
    def current_entry_region(self) -> datetime | None:
        return self._current_entry_region

    @property
    def current_entry_position(self) -> int | None:
        return self._current_entry_position

    @property
    def current_entry_price(self) -> float | None:
        return self._current_entry_price

    @property
    def partials_filled(self) -> list[int]:
        return list(self._partials_filled)

    @property
    def reentry_armed(self) -> bool:
        return self._reentry_armed

    @property
    def reentry_done(self) -> bool:
        return self._reentry_done

    # ----------------------------------------------------------------
    # Persistência (F3c) — NÃO salva parciais/reentry (são em memória)
    # ----------------------------------------------------------------
    def save_state(self) -> None:
        if self._store is None:
            return
        self._store.save_session(self._snapshot())
        self._store.save_regions(self._regions.all())

    def _load_state(self) -> None:
        if self._store is None:
            return
        snap = self._store.load_session()
        if snap is not None:
            self._last_sl_time = snap.last_sl_time
            self._trades_today = snap.trades_today
            self._current_day = snap.current_day
            self._current_entry_region = snap.current_entry_region
            self._current_entry_position = snap.current_entry_position

        stored_regions = self._store.load_regions()
        if stored_regions:
            for region in stored_regions:
                self._regions.register(
                    bar_time=region.location.bar_time,
                    high=region.location.high,
                    low=region.location.low,
                    volume=region.location.volume,
                    big_candle=region.location.big_candle,
                    now=region.broken_time or region.location.bar_time,
                )
            for region in stored_regions:
                live = self._regions.get(region.location.bar_time)
                if live is not None:
                    live.phase = region.phase
                    live.is_buy = region.is_buy
                    live.stop_loss = region.stop_loss
                    live.take_profit = region.take_profit
                    live.broken_time = region.broken_time
                    live.rearmed_once = region.rearmed_once

    def _snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            last_sl_time=self._last_sl_time,
            trades_today=self._trades_today,
            current_day=self._current_day,
            current_entry_region=self._current_entry_region,
            current_entry_position=self._current_entry_position,
        )

    # ----------------------------------------------------------------
    # on_bar_closed
    # ----------------------------------------------------------------
    def on_bar_closed(
        self, bar: Bar, zscore: float, now: datetime
    ) -> BarResult:
        det = self._preset.detector
        sess = self._preset.session

        if zscore < det.std_ref:
            return BarResult(
                created=False,
                register_result=RegisterResult.SKIPPED_DUPLICATE,
                skipped_reason=f"z={zscore:.2f} < std_ref={det.std_ref}",
            )

        if det.mute_open_min > 0:
            session_start = datetime.combine(bar.time.date(), sess.window.start)
            mute_until = session_start + timedelta(minutes=det.mute_open_min)
            if bar.time < mute_until:
                return BarResult(
                    created=False,
                    register_result=RegisterResult.SKIPPED_DUPLICATE,
                    skipped_reason=f"mute_open ({det.mute_open_min}min pós-abertura)",
                )

        from engine.domain.strategy.location import TradeLocation
        loc_stub = TradeLocation(
            bar_time=bar.time, high=bar.high, low=bar.low,
            volume=0.0, big_candle=False,
        )
        big = is_big_candle(loc_stub, self._pricing) \
            if self._pricing.use_big_candle_rule else False

        result, region = self._regions.register(
            bar_time=bar.time,
            high=bar.high,
            low=bar.low,
            volume=bar.volume(det.volume_source),
            big_candle=big,
            now=now,
        )
        if region is not None:
            self.save_state()
        return BarResult(
            created=region is not None,
            register_result=result,
            region=region,
        )

    # ----------------------------------------------------------------
    # on_tick — F2c + F5c
    # ----------------------------------------------------------------
    def on_tick(self, snapshot: MarketSnapshot) -> TickDecision:
        now = snapshot.now

        just_broke = self._regions.update_breakouts(
            snapshot,
            stop_level_fn=self._stop_level_fn,
            take_profit_fn=self._take_profit_fn,
        )
        for r in just_broke:
            log.info("breakout", bar_time=r.bar_time.isoformat(),
                     is_buy=r.is_buy, stop=r.stop_loss, tp=r.take_profit)

        expired = self._regions.sweep_expired(now)
        for r in expired:
            log.info("region_expired", bar_time=r.bar_time.isoformat())

        if just_broke or expired:
            self.save_state()

        # F5c: atualiza estado do reforço (armar / detectar retorno)
        reentry_intent = self._maybe_reentry(snapshot)

        blocked = self._session_block_reason(snapshot)
        if blocked is not None:
            return TickDecision(
                intent=None, blocked_reason=blocked,
                new_breakouts=len(just_broke),
                expired=len(expired),
                reentry_intent=reentry_intent,
            )

        gov = self._regions.governing()
        if gov is None:
            return TickDecision(
                intent=None, blocked_reason=None,
                new_breakouts=len(just_broke),
                expired=len(expired),
                reentry_intent=reentry_intent,
            )

        if not self._carry_delay_ok(gov, now):
            return TickDecision(
                intent=None, blocked_reason="carry_delay",
                new_breakouts=len(just_broke),
                expired=len(expired),
                reentry_intent=reentry_intent,
            )

        intent = self._make_intent(gov, snapshot)
        if intent is None:
            return TickDecision(
                intent=None, blocked_reason="not_ready",
                new_breakouts=len(just_broke),
                expired=len(expired),
                reentry_intent=reentry_intent,
            )

        return TickDecision(
            intent=intent,
            new_breakouts=len(just_broke),
            expired=len(expired),
            reentry_intent=reentry_intent,
        )

    # ----------------------------------------------------------------
    # F5c: reforço no retorno à entrada
    # ----------------------------------------------------------------
    def _maybe_reentry(self, snapshot: MarketSnapshot) -> ReentryIntent | None:
        """Detecta se é hora de armar o reforço e, se o preço voltou,
        emite a `ReentryIntent` (o caller materializa a ordem).

        Regras (espelham o EA v4.60):
          1. Só se `use_reentry=True` e `_current_entry_price` existe.
          2. Só se `_reentry_done=False` (1 reforço por trade).
          3. **Armar:** preço avança `arm_points` a favor → `_reentry_armed=True`.
          4. **Emitir:** `_reentry_armed=True` e preço voltou ao `entry_price` →
             `_reentry_done=True`, retorna `ReentryIntent`.
          5. Se `_reentry_done=True`, não faz mais nada.
        """
        risk = self._preset.risk
        if not risk.use_reentry:
            return None
        if self._current_entry_price is None or self._current_is_buy is None:
            return None
        if self._reentry_done:
            return None

        entry = self._current_entry_price
        is_buy = self._current_is_buy

        # 1) Ainda não armou? Checa se o preço avançou o suficiente.
        if not self._reentry_armed:
            arm_points = risk.reentry_arm_points
            if is_buy:
                advanced = snapshot.bid >= entry + arm_points
            else:
                advanced = snapshot.ask <= entry - arm_points
            if advanced:
                self._reentry_armed = True
                log.info(
                    "reentry_armed",
                    entry=entry, is_buy=is_buy,
                    price=snapshot.bid if is_buy else snapshot.ask,
                    arm_points=arm_points,
                )
            return None

        # 2) Armado: checa se o preço voltou ao entry (fill de limite)
        if is_buy:
            filled = snapshot.bid <= entry
        else:
            filled = snapshot.ask >= entry

        if not filled:
            return None

        # 3) Preço voltou → emite ReentryIntent e marca como feito
        self._reentry_done = True
        self._reentry_armed = False
        log.info(
            "reentry_triggered",
            entry=entry, is_buy=is_buy,
            price=snapshot.bid if is_buy else snapshot.ask,
            contracts=risk.reentry_contracts,
        )
        return ReentryIntent(
            entry_price=entry,
            is_buy=is_buy,
            contracts=risk.reentry_contracts,
            tp_points=risk.reentry_tp_points,
            sl_points=risk.reentry_sl_points,
            created_at=snapshot.now,
        )

    # ----------------------------------------------------------------
    # Notificações (F2c + F3b + F3c + F5a + F5c)
    # ----------------------------------------------------------------
    def notify_stop_loss(self, now: datetime) -> None:
        self._last_sl_time = now
        self.save_state()

    def notify_trade_opened(
        self,
        now: datetime,
        region_bar_time: datetime | None = None,
        entry_price: float | None = None,
        is_buy: bool | None = None,
    ) -> None:
        self._maybe_reset_daily(now)
        self._trades_today += 1
        if region_bar_time is not None:
            self._current_entry_region = region_bar_time
        if entry_price is not None:
            self._current_entry_price = entry_price
        if is_buy is not None:
            self._current_is_buy = is_buy
        self._partials_filled = []
        self._reentry_armed = False
        self._reentry_done = False
        self.save_state()

    def notify_position_closed(self, now: datetime) -> None:
        self._current_entry_region = None
        self._current_entry_position = None
        self._current_entry_price = None
        self._current_is_buy = None
        self._partials_filled = []
        self._reentry_armed = False
        self._reentry_done = False
        self.save_state()

    # ----------------------------------------------------------------
    # on_trade_event — F3b + F5a + F5c
    # ----------------------------------------------------------------
    def on_trade_event(self, event: TradeEvent, now: datetime) -> None:
        if isinstance(event, ReentryFilled):
            # F5c: reforço preenchido. `_reentry_done` já foi marcado.
            log.info(
                "trade_event_reentry_filled",
                position=event.position_ticket,
                volume=event.deal.volume,
                price=event.deal.price,
            )
            self.save_state()
            return

        if isinstance(event, ReentryExitFilled):
            # F5c: TP ou SL do reforço executou. Não muda a posição original.
            log.info(
                "trade_event_reentry_exit",
                position=event.position_ticket,
                is_tp=event.is_tp,
                price=event.deal.price,
            )
            self.save_state()
            return

        if isinstance(event, EntryFilled):
            self._current_entry_position = event.position_ticket
            log.info("trade_event_entry", position=event.position_ticket,
                     volume=event.deal.volume, price=event.deal.price)
            self.save_state()
            return

        if isinstance(event, PartialFilled):
            tier = self._infer_tier_from_comment(event.deal.comment)
            if tier is not None and tier not in self._partials_filled:
                self._partials_filled.append(tier)
            log.info("trade_event_partial", position=event.position_ticket,
                     volume=event.deal.volume, remaining=event.remaining_volume,
                     tier=tier, partials_filled=list(self._partials_filled))
            self.save_state()
            return

        if isinstance(event, StopLossHit):
            self._handle_sl(event.position_ticket, now)
            return

        if isinstance(event, TakeProfitHit):
            self._handle_tp(event.position_ticket, now)
            return

        if isinstance(event, PositionClosed):
            self._handle_close(event.position_ticket, now)
            return

    def _infer_tier_from_comment(self, comment: str) -> int | None:
        c = (comment or "").lower()
        if "partial" not in c:
            return None
        for i in (1, 2, 3):
            if f"partial_{i}" in c:
                return i - 1
        return None

    # ----------------------------------------------------------------
    def _handle_sl(self, position_ticket: int, now: datetime) -> None:
        self.notify_stop_loss(now)
        region_time = self._current_entry_region
        self.notify_position_closed(now)
        if region_time is None:
            log.info("trade_event_sl_no_region", position=position_ticket)
            return

        risk = self._preset.risk
        if risk.reuse_sl_signal:
            self._regions.rearm_after_sl(region_time, allow_unlimited=True)
            log.info("trade_event_sl_rearm_unlimited", region=region_time.isoformat())
        elif risk.use_reverse:
            self._regions.rearm_after_sl(region_time, allow_unlimited=False)
            log.info("trade_event_sl_rearm_once", region=region_time.isoformat())
        else:
            self._regions.consume(region_time)
            log.info("trade_event_sl_consume", region=region_time.isoformat())
        self.save_state()

    def _handle_tp(self, position_ticket: int, now: datetime) -> None:
        region_time = self._current_entry_region
        self.notify_position_closed(now)
        if region_time is not None:
            self._regions.consume(region_time)
            log.info("trade_event_tp_consume", region=region_time.isoformat())
        else:
            log.info("trade_event_tp_no_region", position=position_ticket)
        self.save_state()

    def _handle_close(self, position_ticket: int, now: datetime) -> None:
        region_time = self._current_entry_region
        self.notify_position_closed(now)
        if region_time is not None:
            self._regions.consume(region_time)
            log.info("trade_event_close_consume", region=region_time.isoformat())
        self.save_state()

    # ----------------------------------------------------------------
    # Filtros de sessão
    # ----------------------------------------------------------------
    def _session_block_reason(self, snapshot: MarketSnapshot) -> str | None:
        sess = self._preset.session
        now = snapshot.now
        cur_time = now.time()

        if sess.close_outside and not _in_window(
            cur_time, sess.window.start, sess.window.end
        ):
            return "outside_hours"

        if sess.use_entry_block and _in_window(
            cur_time, sess.entry_block.start, sess.entry_block.end
        ):
            return "entry_block"

        if self._cooldown_active(now):
            return "cooldown"

        self._maybe_reset_daily(now)
        if sess.max_trades_day > 0 and self._trades_today >= sess.max_trades_day:
            return "daily_limit"

        return None

    def _cooldown_active(self, now: datetime) -> bool:
        sess = self._preset.session
        if sess.cooldown_after_sl_min <= 0 or self._last_sl_time is None:
            return False
        return now < self._last_sl_time + timedelta(minutes=sess.cooldown_after_sl_min)

    def _maybe_reset_daily(self, now: datetime) -> None:
        today = now.date()
        if self._current_day is None or self._current_day.date() != today:
            self._current_day = now
            self._trades_today = 0

    def _carry_delay_ok(self, region: RegionState, now: datetime) -> bool:
        sess = self._preset.session
        if sess.carry_entry_delay_min <= 0:
            return True
        if region.bar_time.date() == now.date():
            return True
        session_start = datetime.combine(now.date(), sess.window.start)
        return now >= session_start + timedelta(minutes=sess.carry_entry_delay_min)

    # ----------------------------------------------------------------
    # Construção do TradeIntent — F2c + F5a
    # ----------------------------------------------------------------
    def _make_intent(
        self, region: RegionState, snapshot: MarketSnapshot
    ) -> TradeIntent | None:
        loc = region.location
        is_buy = region.is_buy
        cfg = self._pricing

        if cfg.entry_mode == PricingEntryMode.IMMEDIATE:
            entry_price = snapshot.ask if is_buy else snapshot.bid
            reason = "immediate"
        else:
            level = entry_level(loc, is_buy, cfg)
            if is_buy:
                if snapshot.ask > level:
                    return None
            else:
                if snapshot.bid < level:
                    return None
            entry_price = level
            reason = "pullback"

        risk = self._preset.risk
        partials = make_partial_specs(
            use_partial_exit=risk.use_partial_exit,
            tiers=risk.tiers,
            exit_type=risk.exit_type,
            partial_points=risk.partial_points,
            partial_percent=risk.partial_percent,
        )

        return TradeIntent(
            region=region,
            is_buy=is_buy,
            entry_price=entry_price,
            stop_loss=region.stop_loss,
            take_profit=region.take_profit,
            volume=0.0,
            as_pending=self._preset.entry.as_pending,
            reason=reason,
            created_at=snapshot.now,
            partials=partials,
        )