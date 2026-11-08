"""Simulador F6-lite — executa a TradingSession contra um book sintético.

NÃO acessa MT5. NÃO usa socket. Consome `EventFeed` (BarEvent | TickEvent)
e devolve `SimulationResult` (trades + equity curve + stats).

Modelo de execução:
  - Fill de limite: quando ask <= entry (compra) ou bid >= entry (venda);
  - Fill de mercado: imediato no entry_price;
  - SL/TP: SL ganha empate (conservador, MT5-style);
  - Parciais: F8 — fill quando bid/ask atinge o alvo do tier;
  - Reforço: F8 — fill quando preço avança e volta ao entry;
  - Volume: sizing fixo (by_risk fica para F5);
  - Fim do dia: fecha posições abertas no último tick antes do fechamento.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import structlog

from engine.application.events import BarEvent, EventFeed, TickEvent
from engine.application.intent import TradeIntent
from engine.application.partial_spec import make_partial_specs
from engine.application.trading_session import TradingSession
from engine.config.presets import SizingMode, StdDevV510Preset
from engine.domain.shared.types import MarketSnapshot
from engine.domain.strategy.location import RegionPhase
from engine.config.presets import PartialExitType, SizingMode, StdDevV510Preset

log = structlog.get_logger()


class ExitReason(str, Enum):
    """Motivo do fechamento de um trade."""
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    PARTIAL = "partial"
    END_OF_DAY = "end_of_day"


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    """Um preenchimento (entrada, parcial, SL, TP, reforço)."""
    time: datetime
    price: float
    volume: float
    reason: ExitReason | None = None  # None = entrada (ou reforço)


@dataclass(frozen=True, slots=True)
class SimulatedTrade:
    """Trade completo (entrada + saídas)."""
    region_bar_time: datetime
    is_buy: bool
    entry_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    initial_volume: float
    fills: list[SimulatedFill]      # saídas parciais + final
    pnl_points: float               # soma (saída - entrada) * volume, com sinal
    pnl_money: float                # pnl_points * lot_size * tick_value (aprox)
    exit_reason: ExitReason

    @property
    def is_closed(self) -> bool:
        return self.exit_reason in (
            ExitReason.STOP_LOSS, ExitReason.TAKE_PROFIT, ExitReason.END_OF_DAY,
        ) or self.exit_reason == ExitReason.PARTIAL


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Resultado completo da simulação."""
    trades: list[SimulatedTrade]
    equity_curve: list[tuple[datetime, float]]   # (time, balance)
    stats: dict[str, float | int]


#+------------------------------------------------------------------+
#| SimulatedExecutor — book sintético                              |
#+------------------------------------------------------------------+
class _OpenTrade:
    """Estado interno de um trade aberto no simulador."""
    __slots__ = ("intent", "entry_time", "entry_price", "stop_loss",
                 "take_profit", "initial_volume", "remaining_volume",
                 "fills", "partials_done",
                 "max_favorable", "min_favorable", "reentry_armed", "reentry_done")

    def __init__(self, intent: TradeIntent, entry_time: datetime, fill_price: float):
        self.intent = intent
        self.entry_time = entry_time
        self.entry_price = fill_price
        self.stop_loss = intent.stop_loss
        self.take_profit = intent.take_profit
        self.initial_volume = intent.volume
        self.remaining_volume = intent.volume
        self.fills: list[SimulatedFill] = []
        self.partials_done: list[int] = []
        
        # F8 — Reforço
        self.max_favorable = fill_price
        self.min_favorable = fill_price
        self.reentry_armed = False
        self.reentry_done = False


class SimulatedExecutor:
    """Executa TradeIntents contra o book sintético.

    Estado:
      - _open: trade aberto (no máximo 1 por sessão, como no EA com max_positions=1)
      - _pending_limit: intent aguardando pullback (ainda não filled)
      - _balance: equity acumulado
    """

    def __init__(
        self,
        preset: StdDevV510Preset,
        initial_balance: float = 100_000.0,
        *,
        slippage_points: float = 0.0,
        spread_points: float = 0.0,
    ):
        if slippage_points < 0:
            raise ValueError("slippage_points deve ser >= 0")
        if spread_points < 0:
            raise ValueError("spread_points deve ser >= 0")
        self._preset = preset
        self._balance = initial_balance
        self._slippage = slippage_points
        self._spread = spread_points
        self._open: _OpenTrade | None = None
        self._pending_limit: TradeIntent | None = None
        self._closed: list[SimulatedTrade] = []
        self._equity: list[tuple[datetime, float]] = [(datetime(2000, 1, 1), initial_balance)]

    # ----------------------------------------------------------------
    # Execução do TradeIntent
    # ----------------------------------------------------------------
    def execute(self, intent: TradeIntent, snapshot: MarketSnapshot) -> None:
        """Chama quando a TradingSession emite uma TradeIntent."""
        if self._open is not None or self._pending_limit is not None:
            return

        if self._preset.risk.sizing_mode == SizingMode.FIXED_CONTRACTS:
            volume = self._preset.risk.total_contracts * self._preset.risk.lot_per_contract
        else:
            volume = 1.0

        # F8: injeta os partials no intent (para o simulador saber os alvos)
        tiers = getattr(self._preset.risk, "partial_tiers", [])
        partials = make_partial_specs(
            use_partial_exit=self._preset.risk.use_partial_exit,
            tiers=tiers,
            exit_type=getattr(self._preset.risk, "partial_exit_type", PartialExitType.POINTS),
            partial_points=self._preset.risk.partial_points,
            partial_percent=getattr(self._preset.risk, "partial_percent", 0.0),
        )
        intent = TradeIntent(
            region=intent.region,
            is_buy=intent.is_buy,
            entry_price=intent.entry_price,
            stop_loss=intent.stop_loss,
            take_profit=intent.take_profit,
            volume=volume,
            as_pending=intent.as_pending,
            reason=intent.reason,
            created_at=intent.created_at,
            partials=tuple(partials) if partials else None,
        )

        if intent.as_pending:
            self._pending_limit = intent
        else:
            self._fill_market(intent, snapshot)

    def _fill_market(self, intent: TradeIntent, snapshot: MarketSnapshot) -> None:
        """Fill imediato no entry_price (ajustado por slippage)."""
        if intent.is_buy:
            if intent.stop_loss >= intent.entry_price:
                return
            if intent.take_profit > 0 and intent.take_profit <= intent.entry_price:
                return
        else:
            if intent.stop_loss <= intent.entry_price:
                return
            if intent.take_profit > 0 and intent.take_profit >= intent.entry_price:
                return

        if intent.is_buy:
            fill_price = intent.entry_price + self._slippage
        else:
            fill_price = intent.entry_price - self._slippage

        self._open = _OpenTrade(intent, snapshot.now, fill_price)
        log.info("sim_trade_opened", is_buy=intent.is_buy,
                 entry=fill_price, sl=intent.stop_loss,
                 tp=intent.take_profit, volume=intent.volume,
                 slippage=self._slippage)

    # ----------------------------------------------------------------
    # Checagem de fills e stops a cada tick
    # ----------------------------------------------------------------
    def on_tick(self, snapshot: MarketSnapshot) -> None:
        """Chama a cada tick: tenta preencher limite, checa SL/TP, parciais e reforço."""
        # 1. Pending limit?
        if self._pending_limit is not None:
            intent = self._pending_limit
            filled = False
            if intent.is_buy:
                if snapshot.bid <= intent.entry_price:
                    fill_price = intent.entry_price
                    filled = True
            else:
                if snapshot.ask >= intent.entry_price:
                    fill_price = intent.entry_price
                    filled = True
            if filled:
                self._pending_limit = None
                self._fill_market(intent, snapshot)
                if self._open is not None:
                    if intent.is_buy:
                        self._open.entry_price = fill_price + self._slippage
                    else:
                        self._open.entry_price = fill_price - self._slippage
            return

        # 2. Trade aberto? Checa SL/TP
        if self._open is None:
            return

        trade = self._open
        is_buy = trade.intent.is_buy

        # F8 — Atualiza máximo/mínimo a favor (para armar o reforço)
        if is_buy:
            trade.max_favorable = max(trade.max_favorable, snapshot.bid)
            trade.min_favorable = min(trade.min_favorable, snapshot.ask)
        else:
            trade.min_favorable = min(trade.min_favorable, snapshot.ask)
            trade.max_favorable = max(trade.max_favorable, snapshot.bid)

        # F8 — Checa Reforço (antes de SL/TP, pois pode mudar a posição)
        if self._preset.risk.use_reentry and not trade.reentry_done:
            arm_dist = self._preset.risk.reentry_arm_points
            if not trade.reentry_armed:
                if is_buy and (trade.max_favorable - trade.entry_price) >= arm_dist:
                    trade.reentry_armed = True
                    log.info("sim_reentry_armed", is_buy=is_buy, entry=trade.entry_price)
                elif not is_buy and (trade.entry_price - trade.min_favorable) >= arm_dist:
                    trade.reentry_armed = True
                    log.info("sim_reentry_armed", is_buy=is_buy, entry=trade.entry_price)
            elif trade.reentry_armed:
                # Já armado: verifica se voltou ao entry para disparar
                if is_buy and snapshot.ask <= trade.entry_price:
                    self._execute_reentry(trade, snapshot)
                elif not is_buy and snapshot.bid >= trade.entry_price:
                    self._execute_reentry(trade, snapshot)

        # F8 — Checa Parciais (após o trade estar aberto)
        if trade.intent.partials:
            for idx, partial in enumerate(trade.intent.partials):
                if idx in trade.partials_done:
                    continue
                target = partial.target_price(trade.entry_price, is_buy, "take_profit")
                hit = False
                if is_buy and snapshot.bid >= target:
                    hit = True
                elif not is_buy and snapshot.ask <= target:
                    hit = True

                if hit:
                    vol = partial.contracts * self._preset.risk.lot_per_contract
                    vol = min(vol, trade.remaining_volume)
                    if vol > 0:
                        trade.remaining_volume -= vol
                        trade.partials_done.append(idx)
                        trade.fills.append(SimulatedFill(
                            time=snapshot.now, price=target,
                            volume=vol, reason=ExitReason.PARTIAL,
                        ))
                        log.info("sim_partial_filled", tier=idx, price=target, volume=vol)

                        # Breakeven após Tier 1
                        if idx == 0 and self._preset.risk.breakeven_after_partial:
                            trade.stop_loss = trade.entry_price
                            log.info("sim_breakeven_set", new_sl=trade.entry_price)

                        if trade.remaining_volume <= 0:
                            # Parcial zerou tudo
                            self._finalize_trade(trade, snapshot, ExitReason.PARTIAL)
                            return

        # F8 — Após parciais e reforço, checa SL/TP no volume restante
        if trade.remaining_volume <= 0:
            return

        sl_hit = False
        tp_hit = False
        if is_buy:
            sl_hit = snapshot.bid <= trade.stop_loss
            tp_hit = trade.take_profit > 0 and snapshot.bid >= trade.take_profit
        else:
            sl_hit = snapshot.ask >= trade.stop_loss
            tp_hit = trade.take_profit > 0 and snapshot.ask <= trade.take_profit

        if sl_hit:
            self._close_trade(snapshot, trade.stop_loss, ExitReason.STOP_LOSS)
        elif tp_hit:
            self._close_trade(snapshot, trade.take_profit, ExitReason.TAKE_PROFIT)

    def _execute_reentry(self, trade: _OpenTrade, snapshot: MarketSnapshot) -> None:
        """Executa o reforço (F8)."""
        trade.reentry_done = True
        trade.reentry_armed = False
        # O reforço adiciona contratos, com TP/SL próprios.
        # Simplificação: o novo volume herda o TP/SL original (que já pode ter ido a BE).
        vol = self._preset.risk.reentry_contracts * self._preset.risk.lot_per_contract
        # Nota: O ideal é ter uma sub-posição separada, mas para simplificar,
        # somamos ao volume e ajustamos a média.
        trade.remaining_volume += vol
        trade.initial_volume += vol
        # Ajusta o TP/SL do reforço (ele tem os próprios, mas o simulador não
        # rastreia sub-posições. Usaremos os do preset para o trade como um todo).
        # trade.take_profit = entry + reentry_tp_points
        # trade.stop_loss = entry - reentry_sl_points
        log.info("sim_reentry_filled", volume=vol, entry=trade.entry_price)

    def _finalize_trade(self, trade: _OpenTrade, snapshot: MarketSnapshot, reason: ExitReason) -> None:
        self._open = None
        sign = 1.0 if trade.intent.is_buy else -1.0
        pnl_points = sum(
            sign * (f.price - trade.entry_price) * f.volume
            for f in trade.fills
        )
        pnl_money = pnl_points * self._preset.risk.lot_per_contract
        self._balance += pnl_money
        self._equity.append((snapshot.now, self._balance))

        closed = SimulatedTrade(
            region_bar_time=trade.intent.region.bar_time,
            is_buy=trade.intent.is_buy,
            entry_time=trade.entry_time,
            entry_price=trade.entry_price,
            stop_loss=trade.intent.stop_loss,
            take_profit=trade.intent.take_profit,
            initial_volume=trade.intent.volume,
            fills=list(trade.fills),
            pnl_points=pnl_points,
            pnl_money=pnl_money,
            exit_reason=reason,
        )
        self._closed.append(closed)
        log.info("sim_trade_closed", reason=reason.value,
                 pnl_points=round(pnl_points, 2), pnl_money=round(pnl_money, 2),
                 balance=round(self._balance, 2))

    # ----------------------------------------------------------------
    # Fechamentos
    # ----------------------------------------------------------------
    def _close_trade(
        self,
        snapshot: MarketSnapshot,
        exit_price: float,
        reason: ExitReason,
    ) -> None:
        if self._open is None:
            return
        trade = self._open
        
        fill = SimulatedFill(
            time=snapshot.now, price=exit_price,
            volume=trade.remaining_volume, reason=reason,
        )
        trade.fills.append(fill)
        trade.remaining_volume = 0
        self._finalize_trade(trade, snapshot, reason)

    def force_close_at_end_of_day(self, snapshot: MarketSnapshot) -> None:
        """Fecha trade aberto a mercado no fim do dia."""
        if self._open is None:
            return
        trade = self._open
        is_buy = trade.intent.is_buy
        exit_price = snapshot.bid if is_buy else snapshot.ask
        self._close_trade(snapshot, exit_price, ExitReason.END_OF_DAY)

    # ----------------------------------------------------------------
    # Inspeção
    # ----------------------------------------------------------------
    @property
    def open_trade(self) -> _OpenTrade | None:
        return self._open

    @property
    def pending_limit(self) -> TradeIntent | None:
        return self._pending_limit

    @property
    def trades(self) -> list[SimulatedTrade]:
        return list(self._closed)

    @property
    def balance(self) -> float:
        return self._balance

    @property
    def equity(self) -> list[tuple[datetime, float]]:
        return list(self._equity)


#+------------------------------------------------------------------+
#| Entry point                                                      |
#+------------------------------------------------------------------+
def run_simulation(
    feed: EventFeed,
    preset: StdDevV510Preset,
    *,
    session: TradingSession | None = None,
    initial_balance: float = 100_000.0,
    slippage_points: float = 0.0,
    spread_points: float = 0.0,
) -> SimulationResult:
    """Roda a simulação completa."""
    sess = session or TradingSession(preset)
    executor = SimulatedExecutor(
        preset,
        initial_balance=initial_balance,
        slippage_points=slippage_points,
        spread_points=spread_points,
    )

    last_tick: MarketSnapshot | None = None
    last_open_state = False

    for event in feed:
        if isinstance(event, BarEvent):
            sess.on_bar_closed(event.bar, event.zscore, event.bar.time)
        elif isinstance(event, TickEvent):
            snapshot = event.snapshot
            last_tick = snapshot

            decision = sess.on_tick(snapshot)
            if decision.intent is not None:
                executor.execute(decision.intent, snapshot)

            executor.on_tick(snapshot)

            now_open = executor.open_trade is not None
            if last_open_state and not now_open:
                last_trade = executor.trades[-1] if executor.trades else None
                if last_trade is not None:
                    if last_trade.exit_reason == ExitReason.STOP_LOSS:
                        sess.notify_stop_loss(snapshot.now)
                    sess.notify_trade_opened(snapshot.now)
            last_open_state = now_open

            if preset.session.close_outside:
                cur_time = snapshot.now.time()
                if not _in_window(cur_time,
                                  preset.session.window.start,
                                  preset.session.window.end):
                    executor.force_close_at_end_of_day(snapshot)

    if last_tick is not None and executor.open_trade is not None:
        executor.force_close_at_end_of_day(last_tick)

    trades = executor.trades
    stats = _compute_stats(trades, initial_balance, executor.balance)
    return SimulationResult(
        trades=trades,
        equity_curve=executor.equity,
        stats=stats,
    )


def _in_window(now, start, end) -> bool:  # type: ignore[no-untyped-def]
    if start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


def _compute_stats(
    trades: list[SimulatedTrade],
    initial_balance: float,
    final_balance: float,
) -> dict[str, float | int]:
    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0,
            "win_rate": 0.0,
            "total_pnl_money": 0.0,
            "return_pct": 0.0,
            "winners": 0,
            "losers": 0,
        }
    winners = [t for t in trades if t.pnl_money > 0]
    losers = [t for t in trades if t.pnl_money < 0]
    total = sum(t.pnl_money for t in trades)
    return {
        "n_trades": n,
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": len(winners) / n if n else 0.0,
        "total_pnl_money": total,
        "return_pct": (final_balance - initial_balance) / initial_balance * 100.0,
    }