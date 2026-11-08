"""CLI do motor: engine status | check-config | run | shadow | version."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog

from engine import __version__
from engine.application.executor import RealExecutor
from engine.application.poller import TradeEventPoller
from engine.application.shadow import ShadowComparer
from engine.application.status import get_status
from engine.application.trade_events import PartialFilled
from engine.application.trading_session import TradingSession
from engine.config.presets import load_preset
from engine.config.settings import EngineSettings
from engine.domain.shared.types import MarketSnapshot
from engine.domain.strategy.detector import VolumeStdDetector
from engine.infrastructure.logging.setup import setup_logging
from engine.infrastructure.mt5.fake import FakeGateway
from engine.infrastructure.mt5.gateway import (
    BrokerGateway,
    MT5NotAvailableError,
    RealMT5Gateway,
)
from engine.infrastructure.state.sqlite_store import SqliteStateStore
from engine.application.intent import ReentryIntent
from engine.application.trade_events import ReentryFilled
from engine.application.registry import StrategyRegistry
from engine.domain.strategy.strategy import StrategyConfig
from engine.application.backtester import Backtester
from engine.infrastructure.data.csv_loader import load_bars_csv

log = structlog.get_logger()


#+------------------------------------------------------------------+
#| Subcomandos                                                      |
#+------------------------------------------------------------------+
def cmd_status(args: argparse.Namespace, settings: EngineSettings) -> int:
    preset = load_preset(args.preset or settings.preset)
    gw = FakeGateway() if args.fake else RealMT5Gateway(settings.mt5)
    try:
        gw.connect()
    except MT5NotAvailableError as exc:
        log.error("mt5_indisponivel", detalhe=str(exc))
        return 2
    try:
        st = get_status(gw, settings.mt5.symbol, preset)
    finally:
        gw.shutdown()

    log.info("engine_status",
             versao=__version__,
             preset=preset.name,
             conta=st.account.login, servidor=st.account.server,
             saldo=f"{st.account.balance:,.2f} {st.account.currency}",
             simbolo=st.symbol, candles=st.bars_loaded,
             ultimo_candle=st.last_bar_time, fechamento=st.last_close)
    if st.reading:
        log.info("detector",
                 z=round(st.reading.zscore, 2),
                 media=round(st.reading.mean, 1),
                 desvio=round(st.reading.std, 1),
                 volume=st.reading.volume,
                 candle_sinal=st.reading.is_signal)
    else:
        log.info("detector", estado="janela incompleta (aguardando historico)")
    return 0


def cmd_check_config(args: argparse.Namespace, settings: EngineSettings) -> int:
    preset = load_preset(args.preset or settings.preset)
    log.info(
        "preset_valido",
        nome=preset.name,
        estrategia=preset.strategy,
        detector=preset.detector.model_dump(mode="json"),
        session=preset.session.model_dump(mode="json"),
        entry=preset.entry.model_dump(mode="json"),
        stop=preset.stop.model_dump(mode="json"),
        take_profit=preset.take_profit.model_dump(mode="json"),
        risk=preset.risk.model_dump(mode="json"),
        regions=preset.regions.model_dump(mode="json"),
    )
    return 0


def cmd_run(args: argparse.Namespace, settings: EngineSettings) -> int:
    """Loop principal — conecta, processa ticks, decide, executa.

    F5f: suporta N estratégias em paralelo.
    F11: suporta N símbolos em paralelo (--symbols=WIN$N,WDO$N).

    Flags:
      --strategies=A,B: nomes das estratégias (default: todas do registry)
      --symbols=WIN$N,WDO$N: símbolos (default: o do .env)
      --dry-run: usa FakeGateway
      --fast: não dorme entre iterações
      --max-ticks N: para após N iterações
      --db PATH: SQLite (default: engine.db)
    """
    # ------------------------------------------------------------------
    # 1. Resolver estratégias
    # ------------------------------------------------------------------
    preset = load_preset(args.preset or settings.preset)
    base_name = preset.strategy  # "stddev_v510" (tipo), não "v510_default" (nome)

    registry = StrategyRegistry()
    registry.register(StrategyConfig(
        name=base_name,
        preset=preset,
        magic=0,
    ))

    names_arg = getattr(args, "strategies", None)
    names: list[str] | None = None
    if names_arg:
        names = [n.strip() for n in names_arg.split(",") if n.strip()]

    try:
        configs = registry.resolve(names)
    except (KeyError, ValueError) as exc:
        log.error("strategy_resolve_falhou", erro=str(exc))
        return 2

    # ------------------------------------------------------------------
    # 1.5. Resolver símbolos (F11)
    # ------------------------------------------------------------------
    symbols_arg = getattr(args, "symbols", None)
    if symbols_arg:
        symbols = [s.strip() for s in symbols_arg.split(",") if s.strip()]
    else:
        symbols = [settings.mt5.symbol]

    # ------------------------------------------------------------------
    # 2. Criar gateway
    # ------------------------------------------------------------------
    gw: BrokerGateway
    if args.dry_run:
        gw = FakeGateway()
    else:
        gw = RealMT5Gateway(settings.mt5)

    try:
        gw.connect()
    except MT5NotAvailableError as exc:
        log.error("mt5_indisponivel", detalhe=str(exc))
        return 2

    # ------------------------------------------------------------------
    # 3. Criar N sessões (uma por estratégia × símbolo)
    # ------------------------------------------------------------------
    from engine.domain.risk.exchange_calendar import B3Calendar
    calendar = B3Calendar()

    sessions: list[dict] = []
    for cfg in configs:
        for symbol in symbols:
            store = SqliteStateStore(args.db or "engine.db")
            session = TradingSession(
                cfg.preset,
                symbol=symbol,  # F11: passa o símbolo
                state_store=store,
                calendar=calendar,
            )
            executor = RealExecutor(gw, cfg.preset)
            poller = TradeEventPoller()
            detector = VolumeStdDetector(
                length=cfg.preset.detector.length,
                std_ref=cfg.preset.detector.std_ref,
                source=cfg.preset.detector.volume_source,
            )
            sessions.append({
                "config": cfg,
                "store": store,
                "session": session,
                "executor": executor,
                "poller": poller,
                "detector": detector,
                "symbol": symbol,  # F11: símbolo desta sessão
                "magic": cfg.magic,
                "last_bar_time": None,
                "last_poll_time": datetime.now(tz=timezone.utc) - timedelta(minutes=5),
                "pending_reentry": None,
                "breakeven_applied": False,
            })
            log.info(
                "strategy_session_created",
                name=cfg.name, magic=cfg.magic,
                preset=cfg.preset.name,
                symbol=symbol,
            )

    sleep_s = 0.0 if args.fast else (args.poll_interval or 1.0)
    max_ticks = args.max_ticks or 0
    ticks = 0
    end_of_day_done_today: dict[str, datetime] = {}

    log.info(
        "engine_run_start",
        symbols=symbols, dry_run=args.dry_run,
        n_strategies=len(configs),
        n_sessions=len(sessions),
        strategies=[c.name for c in configs],
        max_ticks=max_ticks, poll_interval=sleep_s,
    )

    # ------------------------------------------------------------------
    # 4. Loop principal
    # ------------------------------------------------------------------
    try:
        while True:
            ticks += 1
            if max_ticks > 0 and ticks > max_ticks:
                log.info("engine_run_max_ticks", ticks=ticks)
                break

            # Para cada símbolo, busca o tick e processa as sessões daquele símbolo
            for symbol in symbols:
                try:
                    tick = gw.symbol_info_tick(symbol)
                except Exception as exc:  # noqa: BLE001
                    log.warning("tick_falhou", symbol=symbol, erro=str(exc))
                    continue

                now = tick.time
                snapshot = MarketSnapshot(ask=tick.ask, bid=tick.bid, now=now)

                # Bars fechadas
                try:
                    bars = gw.closed_bars(symbol, preset.detector.timeframe, 1)
                except Exception as exc:  # noqa: BLE001
                    log.warning("bars_falhou", symbol=symbol, erro=str(exc))
                    bars = []

                # Processa todas as sessões deste símbolo
                for st in sessions:
                    if st["symbol"] != symbol:
                        continue
                    _process_strategy_tick(
                        st=st,
                        gw=gw,
                        symbol=symbol,
                        snapshot=snapshot,
                        bars=bars,
                        end_of_day_done_today=end_of_day_done_today,
                    )

            if sleep_s > 0:
                time.sleep(sleep_s)

    except KeyboardInterrupt:
        log.info("engine_run_interrupted")
    finally:
        for st in sessions:
            try:
                st["session"].save_state()
            except Exception:  # noqa: BLE001
                pass
            st["store"].close()
        gw.shutdown()

    return 0


#+------------------------------------------------------------------+
#| F5f/F11: processa 1 tick para 1 sessão (estratégia × símbolo)    |
#+------------------------------------------------------------------+
def _process_strategy_tick(
    *,
    st: dict,
    gw: BrokerGateway,
    symbol: str,
    snapshot: MarketSnapshot,
    bars: list,
    end_of_day_done_today: dict[str, datetime],
) -> None:
    """Processa 1 tick para 1 sessão (estratégia × símbolo)."""
    cfg = st["config"]
    session = st["session"]
    executor = st["executor"]
    poller = st["poller"]
    detector = st["detector"]
    magic = st["magic"]
    now = snapshot.now

    # 1. Novo candle fechado?
    if bars:
        last = bars[0]
        if st["last_bar_time"] is None or last.time > st["last_bar_time"]:
            st["last_bar_time"] = last.time
            reading = detector.on_bar_closed(last)
            if reading is not None:
                session.on_bar_closed(last, reading.zscore, now)

    # 2. on_tick → TradeIntent
    decision = session.on_tick(snapshot)

    if decision.intent is not None:
        result = executor.execute(decision.intent, symbol=symbol)
        if result.is_ok:
            session.notify_trade_opened(
                now=snapshot.now,
                region_bar_time=decision.intent.bar_time,
                entry_price=decision.intent.entry_price,
                is_buy=decision.intent.is_buy,
            )
            st["breakeven_applied"] = False
            if decision.intent.partials:
                executor.place_partial_orders(
                    decision.intent, symbol=symbol,
                )

    # 3. F5c: reforço
    if decision.reentry_intent is not None:
        ri = decision.reentry_intent
        reentry_res = executor.place_reentry_order(
            symbol=symbol,
            price=ri.entry_price,
            is_buy=ri.is_buy,
            contracts=ri.contracts,
        )
        if reentry_res.is_ok:
            st["pending_reentry"] = ri
            log.info(
                "engine_reentry_order",
                strategy=cfg.name,
                symbol=symbol,
                price=ri.entry_price, is_buy=ri.is_buy,
                contracts=ri.contracts,
                ticket=reentry_res.order_ticket,
            )

    # 4. Poller
    try:
        events = poller.poll(
            gw, since=st["last_poll_time"], symbol=symbol, magic=magic,
        )
        st["last_poll_time"] = now
    except Exception as exc:  # noqa: BLE001
        log.warning("poller_falhou", strategy=cfg.name, symbol=symbol, erro=str(exc))
        events = []

    for ev in events:
        session.on_trade_event(ev, now=now)

        # F5c: reforço preenchido → arma TP/SL
        if isinstance(ev, ReentryFilled) and st["pending_reentry"] is not None:
            ri = st["pending_reentry"]
            executor.place_reentry_exits(
                symbol=symbol,
                entry_price=ri.entry_price,
                is_buy=ri.is_buy,
                contracts=ri.contracts,
                tp_points=ri.tp_points,
                sl_points=ri.sl_points,
            )
            st["pending_reentry"] = None

        # F5a: breakeven após Tier 1
        if (isinstance(ev, PartialFilled)
                and cfg.preset.risk.breakeven_after_partial
                and not st["breakeven_applied"]):
            tier = session._infer_tier_from_comment(ev.deal.comment)
            if tier == 0 and session.current_entry_position is not None:
                pos = session.current_entry_position
                positions = gw.positions(symbol)
                current_tp = 0.0
                for p in positions:
                    if p.ticket == pos:
                        current_tp = p.take_profit
                        break
                be_price = session.current_entry_price or 0.0
                if be_price > 0:
                    modify = executor.modify(
                        pos, stop_loss=be_price, take_profit=current_tp,
                    )
                    if modify.is_ok:
                        st["breakeven_applied"] = True
                        log.info(
                            "breakeven_applied",
                            strategy=cfg.name,
                            symbol=symbol,
                            position=pos, price=be_price,
                        )

    # 5. Fim do dia
    if cfg.preset.session.close_outside:
        cur_time = now.time()
        sess_window = cfg.preset.session.window
        in_window = (
            sess_window.start <= cur_time < sess_window.end
            if sess_window.start < sess_window.end
            else cur_time >= sess_window.start or cur_time < sess_window.end
        )
        if not in_window:
            today = now.date()
            key = f"{cfg.name}:{symbol}"
            last = end_of_day_done_today.get(key)
            if last is None or last.date() != today:
                end_of_day_done_today[key] = now
                results = executor.close_all_at_end_of_day(symbol, now)
                for r in results:
                    if r.is_ok:
                        session.notify_position_closed(now)
                log.info(
                    "end_of_day_closed",
                    strategy=cfg.name,
                    symbol=symbol,
                    n=len(results),
                )

    # 6. Persiste
    session.save_state()


def cmd_shadow(args: argparse.Namespace, settings: EngineSettings) -> int:
    """Roda o motor Python em paralelo ao EA e gera relatório de divergências."""
    ea_magic = args.ea_magic
    py_magic = args.py_magic
    duration_min = args.duration

    preset = load_preset(args.preset or settings.preset)
    symbol = settings.mt5.symbol
    gw = RealMT5Gateway(settings.mt5)
    try:
        gw.connect()
    except MT5NotAvailableError as exc:
        log.error("mt5_indisponivel", detalhe=str(exc))
        return 2

    store = SqliteStateStore(args.db or "engine_shadow.db")
    session = TradingSession(preset, symbol=symbol, state_store=store)
    executor = RealExecutor(gw, preset)
    poller = TradeEventPoller()
    detector = VolumeStdDetector(
        length=preset.detector.length,
        std_ref=preset.detector.std_ref,
        source=preset.detector.volume_source,
    )

    start = datetime.now(tz=timezone.utc)
    end = start + timedelta(minutes=duration_min)
    py_trades: list = []
    last_bar_time: datetime | None = None
    last_poll_time = start - timedelta(minutes=5)

    log.info("shadow_start", symbol=symbol,
             ea_magic=ea_magic, py_magic=py_magic,
             duration_min=duration_min)

    try:
        while datetime.now(tz=timezone.utc) < end:
            tick = gw.symbol_info_tick(symbol)
            now = tick.time
            snapshot = MarketSnapshot(ask=tick.ask, bid=tick.bid, now=now)

            bars = gw.closed_bars(symbol, preset.detector.timeframe, 1)
            if bars:
                last = bars[0]
                if last_bar_time is None or last.time > last_bar_time:
                    last_bar_time = last.time
                    reading = detector.on_bar_closed(last)
                    if reading is not None:
                        session.on_bar_closed(last, reading.zscore, now)

            decision = session.on_tick(snapshot)
            if decision.intent is not None:
                result = executor.execute(decision.intent, symbol=symbol)
                if result.is_ok:
                    py_trades.append(decision.intent)
                    session.notify_trade_opened(
                        now=snapshot.now,
                        region_bar_time=decision.intent.bar_time,
                    )
                    if decision.intent.partials:
                        executor.place_partial_orders(
                            decision.intent, symbol=symbol,
                        )

            try:
                events = poller.poll(
                    gw, since=last_poll_time, symbol=symbol, magic=py_magic,
                )
                last_poll_time = now
            except Exception as exc:  # noqa: BLE001
                log.warning("poller_falhou", erro=str(exc))
                events = []

            for ev in events:
                session.on_trade_event(ev, now=now)

            session.save_state()
            if args.poll_interval > 0:
                time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        log.info("shadow_interrupted")
    finally:
        session.save_state()
        store.close()

    try:
        ea_deals = gw.history_deals(start, symbol=symbol, magic=ea_magic)
    except Exception as exc:  # noqa: BLE001
        log.warning("history_deals_falhou", erro=str(exc))
        ea_deals = []
    gw.shutdown()

    comparer = ShadowComparer()
    report = comparer.compare(
        ea_deals, py_trades,
        start=start, end=end,
        tolerance_points=args.tolerance_points,
    )

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = start.strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"shadow_{ts}.json"
    out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    log.info(
        "shadow_report",
        matched=report.matched,
        ea_only=report.ea_only,
        py_only=report.py_only,
        mismatches=report.mismatches,
        match_rate=round(report.match_rate, 4),
        report=str(out),
    )
    return 0


def cmd_backtest(args: argparse.Namespace, settings: EngineSettings) -> int:
    """Roda backtest sobre um CSV de candles (F6)."""
    from datetime import datetime as _dt

    # Carrega preset
    preset = load_preset(args.preset or settings.preset)

    # Carrega CSV
    csv_path = args.csv
    if not csv_path:
        log.error("backtest_csv_obrigatorio")
        return 2
    try:
        bars = load_bars_csv(csv_path)
    except (FileNotFoundError, ValueError) as exc:
        log.error("backtest_csv_falhou", erro=str(exc))
        return 2

    if not bars:
        log.error("backtest_csv_vazio")
        return 2

    # Filtra por data (opcional)
    if args.from_date:
        try:
            dt_from = _dt.fromisoformat(args.from_date).replace(tzinfo=bars[0].time.tzinfo)
        except ValueError as exc:
            log.error("backtest_from_invalido", erro=str(exc))
            return 2
        bars = [b for b in bars if b.time >= dt_from]

    if args.to_date:
        try:
            dt_to = _dt.fromisoformat(args.to_date).replace(tzinfo=bars[0].time.tzinfo)
        except ValueError as exc:
            log.error("backtest_to_invalido", erro=str(exc))
            return 2
        bars = [b for b in bars if b.time <= dt_to]

    if not bars:
        log.error("backtest_sem_barras_no_periodo")
        return 2

    # Roda backtest
    bt = Backtester(
        preset,
        initial_balance=args.initial_balance,
        slippage_points=args.slippage,
        spread_points=args.spread,
    )
    result = bt.run(bars)

    # Log resumido
    stats = result.simulation.stats
    log.info(
        "backtest_result",
        preset=preset.name,
        n_bars=result.n_bars,
        start=result.start.isoformat(),
        end=result.end.isoformat(),
        n_trades=stats.get("n_trades", 0),
        winners=stats.get("winners", 0),
        losers=stats.get("losers", 0),
        win_rate=round(stats.get("win_rate", 0.0), 4),
        total_pnl=round(stats.get("total_pnl_money", 0.0), 2),
        return_pct=round(stats.get("return_pct", 0.0), 2),
        sharpe=round(result.metrics["sharpe"], 4),
        max_drawdown_pct=round(result.metrics["max_drawdown_pct"], 2),
        profit_factor=(
            "inf" if result.metrics["profit_factor"] == float("inf")
            else round(result.metrics["profit_factor"], 4)
        ),
    )

    # Exporta trades + equity (opcional)
    if args.output:
        from pathlib import Path
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "preset": preset.name,
            "start": result.start.isoformat(),
            "end": result.end.isoformat(),
            "n_bars": result.n_bars,
            "n_trades": len(result.simulation.trades),
            "stats": result.simulation.stats,
            "metrics": {
                k: ("inf" if v == float("inf") else v)
                for k, v in result.metrics.items()
            },
            "trades": [
                {
                    "region_bar_time": t.region_bar_time.isoformat(),
                    "is_buy": t.is_buy,
                    "entry_time": t.entry_time.isoformat(),
                    "entry_price": t.entry_price,
                    "stop_loss": t.stop_loss,
                    "take_profit": t.take_profit,
                    "initial_volume": t.initial_volume,
                    "pnl_points": t.pnl_points,
                    "pnl_money": t.pnl_money,
                    "exit_reason": t.exit_reason.value,
                }
                for t in result.simulation.trades
            ],
            "equity_curve": [
                (ts.isoformat(), bal)
                for ts, bal in result.simulation.equity_curve
            ],
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.info("backtest_output_salvo", path=str(out))

    return 0


#+------------------------------------------------------------------+
#| Main                                                             |
#+------------------------------------------------------------------+
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine", description="Motor de trading")
    parser.add_argument("--json", action="store_true", help="Diario em JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Conta, simbolo e leitura do detector")
    p_status.add_argument("--fake", action="store_true")
    p_status.add_argument("--preset", default=None)

    p_check = sub.add_parser("check-config", help="Valida o preset e mostra os parametros")
    p_check.add_argument("--preset", default=None)

    p_run = sub.add_parser("run", help="Roda o motor em tempo real")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--demo", action="store_true")
    p_run.add_argument("--preset", default=None)
    p_run.add_argument("--db", default="engine.db")
    p_run.add_argument("--poll-interval", type=float, default=1.0)
    p_run.add_argument("--max-ticks", type=int, default=0)
    p_run.add_argument("--fast", action="store_true")
    p_run.add_argument("--strategies", default=None,
                       help="Estratégias separadas por vírgula (default: todas)")
    p_run.add_argument("--symbols", default=None,
                       help="Símbolos separados por vírgula (default: o do .env)")  # F11

    p_shadow = sub.add_parser("shadow", help="Modo sombra: compara decisões com EA")
    p_shadow.add_argument("--ea-magic", type=int, required=True)
    p_shadow.add_argument("--py-magic", type=int, default=0)
    p_shadow.add_argument("--duration", type=int, default=60)
    p_shadow.add_argument("--poll-interval", type=float, default=2.0)
    p_shadow.add_argument("--tolerance-points", type=float, default=2.0)
    p_shadow.add_argument("--report-dir", default="reports")
    p_shadow.add_argument("--db", default="engine_shadow.db")
    p_shadow.add_argument("--preset", default=None)

    p_backtest = sub.add_parser("backtest", help="Roda backtest sobre CSV (F6)")
    p_backtest.add_argument("--csv", required=True,
                            help="Caminho do CSV de candles")
    p_backtest.add_argument("--preset", default=None)
    p_backtest.add_argument("--from-date", default=None,
                            help="Filtra candles a partir de YYYY-MM-DD")
    p_backtest.add_argument("--to-date", default=None,
                            help="Filtra candles até YYYY-MM-DD")
    p_backtest.add_argument("--initial-balance", type=float, default=100_000.0,
                            help="Saldo inicial (default: 100000)")
    p_backtest.add_argument("--slippage", type=float, default=0.0,
                            help="Slippage em pontos (default: 0)")
    p_backtest.add_argument("--spread", type=float, default=0.0,
                            help="Spread em pontos (default: 0)")
    p_backtest.add_argument("--output", default=None,
                            help="Salva resultado em JSON (opcional)")

    sub.add_parser("version", help="Versao do motor")

    args = parser.parse_args(argv)
    settings = EngineSettings()
    setup_logging(json_output=args.json or settings.log_json)

    if args.cmd == "version":
        print(__version__)
        return 0
    if args.cmd == "status":
        return cmd_status(args, settings)
    if args.cmd == "check-config":
        return cmd_check_config(args, settings)
    if args.cmd == "run":
        return cmd_run(args, settings)
    if args.cmd == "backtest":
        return cmd_backtest(args, settings)
    if args.cmd == "shadow":
        return cmd_shadow(args, settings)
    return 1


if __name__ == "__main__":
    sys.exit(main())