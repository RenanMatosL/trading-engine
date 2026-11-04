"""Simulador F6-lite — executa a TradingSession contra um book sintético.

NÃO acessa MT5. NÃO usa socket. Consome `EventFeed` (BarEvent | TickEvent)
e devolve `SimulationResult` (trades + equity curve + stats).

Modelo de execução:
  - Fill de limite: quando ask <= entry (compra) ou bid >= entry (venda);
  - Fill de mercado: imediato no entry_price;
  - SL/TP: SL ganha empate (conservador, MT5-style);
  - Parciais: só se preset.risk.use_partial_exit=True;
  - Volume: sizing fixo (by_risk fica para F5);
  - Fim do dia: fecha posições abertas no último tick antes do fechamento.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import structlog

from engine.application.events import BarEvent, EventFeed, TickEvent
from engine.application.intent import TradeIntent
from engine.application.trading_session import TradingSession
from engine.config.presets import SizingMode, StdDevV510Preset
from engine.domain.shared.types import MarketSnapshot
from engine.domain.strategy.location import RegionPhase

log = structlog.get_logger()


class ExitReason(str, Enum):
    """Motivo do fechamento de um trade."""
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    PARTIAL = "partial"
    END_OF_DAY = "end_of_day"


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    """Um preenchimento (entrada, parcial, SL, TP)."""
    time: datetime
    price: float
    volume: float
    reason: ExitReason | None = None  # None = entrada


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
                 "fills", "partials_done")

    def __init__(self, intent: TradeIntent, entry_time: datetime, fill_price: float):
        self.intent = intent
        self.entry_time = entry_time
        self.entry_price = fill_price
        self.stop_loss = intent.stop_loss
        self.take_profit = intent.take_profit
        self.initial_volume = intent.volume
        self.remaining_volume = intent.volume
        self.fills: list[SimulatedFill] = []
        self.partials_done: list[int] = []  # índices de tiers já executados


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
        """Chama quando a TradingSession emite uma TradeIntent.

        - as_pending=True: arma limite, aguarda pullback;
        - as_pending=False: fill imediato.
        """
        if self._open is not None or self._pending_limit is not None:
            return  # já há trade/pending ativo — ignora (idempotente)

        # Sizing fixo (F5 implementa by_risk)
        if self._preset.risk.sizing_mode == SizingMode.FIXED_CONTRACTS:
            volume = self._preset.risk.total_contracts * self._preset.risk.lot_per_contract
        else:
            volume = 1.0  # fallback conservador

        # Preenche o volume no intent (frozen → cria novo)
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
        )

        if intent.as_pending:
            self._pending_limit = intent
        else:
            self._fill_market(intent, snapshot)

    def _fill_market(self, intent: TradeIntent, snapshot: MarketSnapshot) -> None:
        """Fill imediato no entry_price (ajustado por slippage)."""
        # Sanity: SL/TP coerentes com is_buy
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

        # F5e: slippage (pior caso — compra paga mais, venda recebe menos)
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
        """Chama a cada tick: tenta preencher limite, checa SL/TP."""
        # 1. Pending limit?
        if self._pending_limit is not None:
            intent = self._pending_limit
            filled = False
            if intent.is_buy:
                # Compra: bid <= entry_price (preço chegou no nível)
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
                # Ajusta o entry_price do trade para o fill real
                # (F5e: aplica slippage no fill de limite também — pior caso)
                if self._open is not None:
                    if intent.is_buy:
                        self._open.entry_price = fill_price + self._slippage
                    else:
                        self._open.entry_price = fill_price - self._slippage
            return  # não checa SL/TP no mesmo tick do fill

        # 2. Trade aberto? Checa SL/TP (SL ganha empate)
        if self._open is None:
            return

        trade = self._open
        is_buy = trade.intent.is_buy

        sl_hit = False
        tp_hit = False
        if is_buy:
            sl_hit = snapshot.bid <= trade.stop_loss
            tp_hit = trade.take_profit > 0 and snapshot.bid >= trade.take_profit
        else:
            sl_hit = snapshot.ask >= trade.stop_loss
            tp_hit = trade.take_profit > 0 and snapshot.ask <= trade.take_profit

        # SL ganha empate
        if sl_hit:
            self._close_trade(snapshot, trade.stop_loss, ExitReason.STOP_LOSS)
        elif tp_hit:
            self._close_trade(snapshot, trade.take_profit, ExitReason.TAKE_PROFIT)

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
        self._open = None

        fill = SimulatedFill(
            time=snapshot.now, price=exit_price,
            volume=trade.remaining_volume, reason=reason,
        )
        trade.fills.append(fill)

        # P&L
        sign = 1.0 if trade.intent.is_buy else -1.0
        pnl_points = sum(
            sign * (f.price - trade.entry_price) * f.volume
            for f in trade.fills
        )

        # pnl_money: aproximação (1 ponto = 1 unidade de preço; tick_value ~ 1)
        # Em F5, usar SymbolInfo do MT5.
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
    """Roda a simulação completa.

    Loop:
      para cada evento:
        se BarEvent: TradingSession.on_bar_closed()
        se TickEvent:
          TradingSession.on_tick() → decision
          se decision.intent: executor.execute(intent, snapshot)
          executor.on_tick(snapshot)  ← checa SL/TP
          notifica sessão de trade fechado (se houver)
      no final: force_close_at_end_of_day se ainda houver trade
    """
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

            # Notifica sessão quando um trade transiciona aberto→fechado
            now_open = executor.open_trade is not None
            if last_open_state and not now_open:
                last_trade = executor.trades[-1] if executor.trades else None
                if last_trade is not None:
                    if last_trade.exit_reason == ExitReason.STOP_LOSS:
                        sess.notify_stop_loss(snapshot.now)
                    sess.notify_trade_opened(snapshot.now)
            last_open_state = now_open

            # Fim do dia: fecha posição aberta
            if preset.session.close_outside:
                cur_time = snapshot.now.time()
                if not _in_window(cur_time,
                                  preset.session.window.start,
                                  preset.session.window.end):
                    executor.force_close_at_end_of_day(snapshot)

    # Se sobrou trade aberto no fim da fita, força fechamento
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