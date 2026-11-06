# AI.md — Guia de Retomada do Projeto Trading Engine

> **Propósito deste arquivo:** permitir que uma IA (ou o autor) retome o projeto
> em outro chat/sessão **sem contexto anterior**, saiba **exatamente** onde
> paramos, o que falta, e o que **não pode ser quebrado**.
>
> **Leia este arquivo INTEIRO antes de escrever qualquer linha de código.**
> Ele evita retrabalho, decisões já tomadas e bugs conhecidos.
>
> **Este arquivo cobre o backend e visão geral.** Para o frontend (FastAPI,
> HTMX, templates), leia o `ai_front_end.md`.

---

## 1. Contexto do projeto

Porte em Python do EA **`StdDevVolumeBreakout.mq5` v4.60** (MQL5) para a API
oficial **MetaTrader5** (pacote `MetaTrader5` pip, só Windows). Arquitetura
**hexagonal + DDD**, com domínio puro e ACL do MT5.

**Objetivo final:** motor multi-estratégia, hoje focado em UMA estratégia
(`stddev_v510`), com paridade bit-a-bit com o EA original, capaz de operar em
conta demo/real via MT5 e comparar resultado com o Strategy Tester do MT5.

**Estratégia (resumo):**
1. Calcula z-score do volume em janela de `InpLen=180` candles M1 fechados.
2. Se `z >= InpStdRef=4.0`, cria uma "região de trade-location" (máx, mín, meio).
3. Aguarda rompimento de um extremo → define direção (compra se rompe máx, venda se rompe mín).
4. Entrada no pullback (meio do candle ou nível configurável), SL, TP.
5. Gerencia regiões com validade (2 pregões), TTL pós-rompimento (60 min),
   cooldown pós-SL (10 min), limite diário (3), filtros de horário e de abertura.
6. **Parciais** (tiers 1/2/3) + breakeven após Tier 1.
7. **Reforço** no retorno à entrada (1x por trade, com TP/SL próprios).
8. **Sizing** fixo ou by-risk (fixed_money / % do balance).
9. **Validade por pregões reais** (calendário B3, feriados 2026-2027).
10. **Multi-estratégia** (N sessões por tick, cada uma com seu magic).
11. **Backtester próprio** (sem MT5, com slippage/spread e métricas).
12. **Interface Web (F7)** (FastAPI + HTMX + Pico CSS) para monitoramento e backtests.

---

## 2. Estado atual (linha do tempo)

| Fase | Descrição | Status |
|---|---|---|
| **F0** | Esqueleto (CLI, config, ACL, fake) | ✅ fechado |
| **F1** | Detector z-score — paridade bit-a-bit vs EA v4.60 | ✅ fechado |
| **F2a** | Preset completo (7 seções) + YAML + validadores cruzados | ✅ fechado |
| **F2b** | RegionManager + TradeLocation + pricing | ✅ fechado |
| **F2c** | TradingSession (filtros de sessão + TradeIntent) | ✅ fechado |
| **F2d** | Simulador F6-lite (EventFeed + SimulatedExecutor) | ✅ fechado |
| **F3a** | RealExecutor + BrokerGateway expandido | ✅ fechado |
| **F3b** | TradeEventPoller + notificações ao TradingSession | ✅ fechado |
| **F3c** | Persistência SQLite (MemoryStore + SqliteStore) | ✅ fechado |
| **F3d** | `engine run` (loop real + demo) + `symbol_info_tick` | ✅ fechado |
| **F4** | Modo sombra (compara decisões com EA em tempo real) | ✅ fechado |
| **F5a** | Parciais (tiers 1/2/3) + breakeven após Tier 1 | ✅ fechado |
| **F5b** | By-risk sizing (fixed_money + percent_balance) | ✅ fechado |
| **F5c** | Reforço no retorno à entrada (`use_reentry`) | ✅ fechado |
| **F5d** | Validade por pregões reais (calendário B3) | ✅ fechado |
| **F5e** | Slippage/spread + `is_stop` + calendar + persistência | ✅ fechado |
| **F5f** | Multi-estratégia (`StrategyConfig` + `StrategyRegistry`) | ✅ fechado |
| **F6** | Backtester próprio (sem MT5, com métricas) | ✅ fechado |
| **F7a** | Frontend: Setup FastAPI + Pico + HTMX + `/api/status` | ✅ fechado |
| **F7b-1** | Frontend: Tabela `trades` no SQLite + `save_trade` | ✅ fechado |
| **F7b-2** | Frontend: Dashboard com equity curve + tabela de trades | ✅ fechado |
| **F7c** | Frontend: Config (edição de preset via formulário) | ✅ fechado |
| **F7d** | Frontend: Backtest (upload CSV + resultado) | ✅ fechado |
| **F7e** | Frontend: Shadow (comparar EA vs Python) | ✅ fechado |

**Suíte de testes atual:** **231 passed** (`uv run pytest -q`).
**Projeto completo (F0→F6 + F7a→F7e).** Próximas fases: F7f (SSE), F7g (testes web adicionais) e F8+ (melhorias no motor).

---

## 3. Arquitetura (mapa de arquivos)
src/engine/
├── domain/ # PURO: zero imports externos
│ ├── shared/types.py # Bar, Side, VolumeSource, MarketSnapshot
│ ├── risk/
│ │ ├── calendar.py # TradingWindow (+ session_shift)
│ │ └── exchange_calendar.py # B3Calendar (feriados 2026-2027) — F5d
│ ├── state/store.py # StateStore (Protocol) + SessionSnapshot + TradeRecord (F3c + F5e + F7b-1)
│ └── strategy/
│ ├── detector.py # VolumeStdDetector (paridade EA, F1)
│ ├── location.py # TradeLocation, RegionState, RegionPhase, RegisterResult
│ ├── regions.py # RegionManager (governança, TTL, validade, rearme)
│ ├── pricing.py # entry_level / stop_level / take_profit_level
│ │ # + PricingConfig + Enums de modo
│ └── strategy.py # StrategyConfig (F5f)
│
├── config/
│ ├── settings.py # EngineSettings (pydantic-settings, .env)
│ └── presets.py # StdDevV510Preset (7 seções + validadores cruzados)
│
├── application/ # orquestração (sem MT5, sem ordens)
│ ├── status.py # get_status (F0/F1)
│ ├── intent.py # TradeIntent, ReentryIntent, TickDecision, BarResult
│ ├── trading_session.py # TradingSession (+ state_store + on_trade_event +
│ │ # calendar + persistência + save_trade)
│ ├── events.py # EventFeed, BarEvent, TickEvent (F2d)
│ ├── simulation.py # run_simulation, SimulatedExecutor
│ │ # + slippage/spread (F5e)
│ ├── trade_events.py # EntryFilled, PartialFilled, ReentryFilled,
│ │ # ReentryExitFilled, StopLossHit,
│ │ # TakeProfitHit, PositionClosed (F3b + F5c)
│ ├── poller.py # TradeEventPoller (F3b + F5c)
│ ├── executor.py # RealExecutor (+ close_all_at_end_of_day +
│ │ # place_partial_orders + place_reentry_* +
│ │ # by-risk sizing + is_stop)
│ ├── shadow_report.py # ShadowReport + Divergence (F4)
│ ├── shadow.py # ShadowComparer (F4)
│ ├── partial_spec.py # PartialSpec + make_partial_specs (F5a)
│ ├── registry.py # StrategyRegistry (F5f)
│ ├── metrics.py # Sharpe, drawdown, win rate, etc (F6)
│ └── backtester.py # Backtester + BacktestResult (F6)
│
├── infrastructure/ # ACL MetaTrader5 + persistência + CSV
│ ├── mt5/
│ │ ├── gateway.py # BrokerGateway (Protocol) + RealMT5Gateway
│ │ │ # + AccountInfo, SymbolInfo, TickInfo,
│ │ │ # PositionInfo, OrderInfo, DealInfo,
│ │ │ # OrderRequest (is_stop em F5e), OrderResult
│ │ └── fake.py # FakeGateway (book sintético + _force_fill_pending)
│ ├── logging/setup.py # structlog
│ ├── state/
│ │ ├── memory_store.py # InMemoryStateStore (F3c + F7b-1)
│ │ └── sqlite_store.py # SqliteStateStore + schema (F3c + F5e + F7b-1)
│ └── data/
│ └── csv_loader.py # load_bars_csv (F6)
│
├── web/ # Frontend (FastAPI) — F7a+
│ ├── app.py # App + rotas HTML + API
│ ├── deps.py # gateway, settings
│ ├── schemas.py # Pydantic schemas
│ ├── routes/ # Routers (trades, equity, preset, backtest, shadow)
│ ├── templates/ # base.html, dashboard.html, partials _*.html
│ └── static/ # htmx, pico, uplot
│
└── cli.py # engine status | check-config | run | shadow |

backtest | version
presets/
└── stddev_v510_default.yaml # todos os inputs do EA v4.60 comentados
tests/
├── fixtures/
│ ├── v510_expected.csv # 679 candles WIN$N M1 + z-score do MT5
│ └── sample_bars.csv # 10 candles (F6)
├── test_calendar.py # TradingWindow + B3Calendar + session_shift (F5d)
├── test_detector.py
├── test_presets.py
├── test_golden_v510.py # paridade bit-a-bit vs EA v4.60
├── test_regions.py # RegionManager + validade por pregões reais
├── test_pricing.py
├── test_trading_session.py
├── test_simulation.py # simulador + slippage/spread (F5e)
├── test_executor.py # executor + by-risk (F5b) + is_stop (F5e)
├── test_poller.py # TradeEventPoller (+ reentry em F5c)
├── test_state.py # StateStore + persistência (F5e + F7b-1)
├── test_run.py
├── test_shadow.py # modo sombra
├── test_partials.py # parciais + integração (F5a)
├── test_reentry.py # reforço (F5c)
├── test_registry.py # StrategyRegistry (F5f)
├── test_csv_loader.py # load_bars_csv (F6)
├── test_metrics.py # métricas (F6)
├── test_backtester.py # Backtester (F6)
└── test_web.py # TestClient FastAPI (F7b-2 a F7e) — 16 testes

text

---

## 4. Decisões de arquitetura (NÃO MUDE SEM MOTIVO FORTE)

### Domínio puro
- `domain/` **não importa** MT5, pydantic, structlog, nem nada externo.
- `MarketSnapshot` em `domain/shared/types.py` é a "foto do mercado" no tick.
- `Bar` representa candle **fechado** (nunca em formação).

### Semântica do detector = EA v4.60 EXATAMENTE
- Janela **inclui** o candle avaliado (`[i-L+1, i]`).
- Desvio **amostral** (n-1).
- Fórmula de uma passada: `var = (sumsq - sum*mean)/(n-1)`.
- **Se mexer nisso, `test_golden_v510.py` falha.** É de propósito.

### `B3Calendar` (F5d)
- Lista **hardcoded** de feriados 2026-2027. Atualiza uma vez por ano.
- `is_trading_day(d)` — segunda a sexta, exceto feriados.
- `trading_days_between(start, end)` — conta pregões (negativo se `start > end`).
- **Não** move feriados que caem em fim de semana.
- **TODO F8+:** atualizar feriados 2028+.

### `TradingWindow.session_shift(bar_time, now, calendar)`
- Retorna `calendar.trading_days_between(bar_time.date(), now.date())`.
- Se `calendar is None`, fallback para **dias corridos** (comportamento antigo).
- **Não** usa `start`/`end` do `TradingWindow` (só `bar_time` e `now`).
- **TODO F8+:** transformar em `@staticmethod`.

### `RegionManager`
- Fila `dict[bar_time, RegionState]`, limite `max_loc=12` (paridade com EA).
- Fila cheia substitui a de **menor volume** (governança por volume).
- `RegionPhase` é **enum explícito** (WAITING_BREAKOUT / BROKEN / CONSUMED / REARMED).
- **NÃO** aplica filtros de sessão (isso é `TradingSession`).
- **F5d:** `__init__` aceita `calendar: B3Calendar | None = None`.
- **F5e:** o `TradingSession` **passa** `B3Calendar()` por default (integração concluída).

### `TradingSession`
- **Não** executa ordens. **Não** consulta MT5.
- Emite `TradeIntent` (frozen) — o `Executor` executa.
- Filtros de sessão em `on_tick`: horário, entry_block, cooldown, daily_limit, carry_delay.
- Filtro de abertura (`mute_open_min`) em `on_bar_closed`.
- Estado: `_last_sl_time`, `_trades_today`, `_current_day`, `_current_entry_region`, `_current_entry_position`, `_current_entry_price`, `_current_is_buy`, `_partials_filled`, `_reentry_armed`, `_reentry_done`.
- **F3b:** `on_trade_event(event, now)` consome `TradeEvent` do poller:
  - `EntryFilled` → rastreia `_current_entry_position`
  - `StopLossHit` → `notify_stop_loss` + rearme/consume da região
  - `TakeProfitHit` / `PositionClosed` → consome a região
  - `PartialFilled` → **F5a:** rastreia tier
  - `ReentryFilled` / `ReentryExitFilled` → **F5c:** apenas loga
- **F3c:** `state_store` opcional no `__init__`. `save_state()` serializa.
- **F5a:** `notify_trade_opened` e `notify_position_closed` **zeram** `_partials_filled`.
- **F5c:** `notify_trade_opened(...)` grava `_current_entry_price` e `_current_is_buy`; `_maybe_reentry(snapshot)` detecta quando armar (`reentry_armed`) e quando disparar (`ReentryIntent`).
- **F5e:** `__init__` aceita `calendar: B3Calendar | None = None`. `SessionSnapshot` agora inclui 5 campos extras.
- **F5f:** o `cmd_run` cria **N** `TradingSession` (uma por estratégia).
- **F7b-1:** `_save_closed_trade` persiste o trade fechado no SQLite (via `state_store`).

### `TradeIntent`
- `volume` = 0.0 até o `Executor` preencher.
- `as_pending=True` → Executor usa BuyLimit/SellLimit.
- `as_pending=False` → Executor usa Buy/Sell (a mercado).
- **F5a:** `partials: tuple[PartialSpec, ...] | None`.

### `ReentryIntent` (F5c)
- Emitida pelo `TradingSession._maybe_reentry` no `TickDecision.reentry_intent`.
- Contém: `entry_price`, `is_buy`, `contracts`, `tp_points`, `sl_points`, `created_at`.
- O `engine run` materializa via `executor.place_reentry_order(...)`.
- No fill (`ReentryFilled`), o `engine run` chama `executor.place_reentry_exits(...)`.
- 1 reforço por trade (`_reentry_done=True`).

### `PartialSpec` (F5a)
- `tier_index`: 0, 1, 2 (Tier 1, 2, 3 do EA).
- `contracts`: quantos contratos sair neste tier.
- `points` + `percent`: alvo em pontos ou % da entrada.
- `target_price(entry, is_buy, exit_type)` → preço-alvo do tier.
- `make_partial_specs(...)` traduz do preset. Tier 1 usa `partial_points`/`partial_percent` global.

### `StrategyConfig` (F5f)
- `name`: identificador único (ex: `stddev_v510`).
- `preset`: `StdDevV510Preset` (validado pelo pydantic).
- `magic`: magic number do MT5 (distingue as ordens).
- `frozen` e serializável.

### `StrategyRegistry` (F5f)
- `register(config)` — falha se nome ou magic duplicado.
- `get(name)` — falha se não existir.
- `list()` — nomes ordenados.
- `resolve(names)` — se `names is None`/vazio, retorna todas.
- `cmd_run` registra o preset principal com `name = preset.strategy` (não `preset.name`).

### `BrokerGateway` (Protocol) + ACL
- Domínio **nunca** importa `MetaTrader5`. Sempre conversa com o Protocol.
- `RealMT5Gateway`: import tardio.
- `FakeGateway`: book sintético para desenvolvimento/testes em qualquer SO.
- **IMPORTANTE:** o `OrderResult` tem `@property is_ok` (não `ok`). O `ExecutionResult` do `executor.py` tem **as duas** (`.is_ok` + `.ok`, alias retrocompatível).
- **F3d:** `TickInfo` (dataclass) + `symbol_info_tick(symbol)` no Protocol e nas duas implementações.
- **F5e:** `OrderRequest.is_stop: bool = False`.
- **`history_deals(since, *, symbol=None, magic=None)`** — normaliza `since` naive para UTC.

### `StateStore` (F3c + F5e + F7b-1)
- `StateStore` é **Protocol** (domínio puro).
- `SessionSnapshot` é `frozen` e serializável (10 campos: `last_sl_time`, `trades_today`, `current_day`, `current_entry_region`, `current_entry_position`, `current_entry_price`, `current_is_buy`, `reentry_armed`, `reentry_done`, `partials_filled`).
- **F5e:** persiste parciais/reforço entre reinícios.
- **F7b-1:** `SqliteStateStore` tem tabela `trades` (TradeRecord). `save_trade()`, `list_trades(limit)`, `list_equity(limit)`.
- Datas sempre ISO 8601 UTC.
- `SqliteStateStore` cria schema no `__init__` (`CREATE TABLE IF NOT EXISTS`).

### `ShadowComparer` (F4)
- `ShadowReport` (frozen): `start`, `end`, `matched`, `ea_only`, `py_only`, `mismatches`, `divergences`.
- `Divergence` (frozen): `kind`, `bar_time`, `is_buy`, `ea_deal`, `py_price`, `detail`.
- Match por `(bar_time, is_buy, entry_price ± tolerance_points)`. Tolerância default 2.0.
- `match_rate = matched / max(total_ea, total_py)`. 1.0 = perfeito.
- Relatório JSON salvo em `reports/shadow_YYYYMMDD_HHMMSS.json`.
- **`ShadowComparer` não acessa MT5.** Só `engine shadow` acessa. A rota web `POST /api/shadow` (F7e) também acessa (mas é **read-only**, não coloca ordens).

### `Backtester` (F6)
- Consome `list[Bar]` (do `csv_loader`).
- Constrói `EventFeed`:
  - `BarEvent(bar, zscore)` para cada candle (z-score via `VolumeStdDetector`).
  - 2 `TickEvent` (open e close) para cada candle.
- Roda `run_simulation(feed, preset, ...)` → `SimulationResult`.
- Calcula métricas via `metrics.py`.
- Retorna `BacktestResult` (simulation + metrics + start + end + n_bars).

### `metrics.py` (F6)
- `sharpe(trades, periods_per_year=252)` — Sharpe ratio (anualizado).
- `max_drawdown(equity_curve)` — max drawdown em %.
- `win_rate(trades)` — fração de trades com lucro.
- `profit_factor(trades)` — lucro bruto / |prejuízo bruto|.
- `average_win_loss(trades)` — (média wins, média losses).
- `total_return(trades, initial_balance)` — retorno total em %.

### `csv_loader.py` (F6)
- `load_bars_csv(path)` — carrega CSV de candles (ISO 8601 ou epoch).
- Header obrigatório: `time,open,high,low,close,tick_volume,real_volume`.
- Retorna `list[Bar]` com timezone UTC.

### `engine run` (F3d + F5a + F5c + F5f)
- Subcomando `run` no `cli.py`.
- Flags: `--dry-run`, `--demo`, `--preset`, `--db`, `--poll-interval`, `--max-ticks`, `--fast`, `--strategies=A,B`.
- **F5f:** o `cmd_run` cria **N** sessões. O loop principal itera **N sessões por tick**.
- **F5a:** após `executor.execute(intent)` OK, chama `executor.place_partial_orders(...)`. Breakeven após Tier 1 (se `breakeven_after_partial=True`), 1x por trade.
- **F5c:** após `decision.reentry_intent`, chama `executor.place_reentry_order(...)` e guarda `pending_reentry`. No `ReentryFilled`, chama `executor.place_reentry_exits(...)`.
- `KeyboardInterrupt` → save_state + shutdown.

### `engine shadow` (F4)
- Subcomando `shadow` no `cli.py`.
- Flags: `--ea-magic` (obrigatório), `--py-magic`, `--duration`, `--poll-interval`, `--tolerance-points`, `--report-dir`, `--db`, `--preset`.
- **Coloca ordens reais no MT5** (com o `py-magic`). Não é read-only.
- **Requer MT5 aberto.** Não funciona com `--dry-run`.

### `engine backtest` (F6)
- Subcomando `backtest` no `cli.py`.
- Flags: `--csv` (obrigatório), `--preset`, `--from-date`, `--to-date`, `--initial-balance`, `--slippage`, `--spread`, `--output` (opcional, JSON).
- Roda `Backtester.run(bars)` → `BacktestResult`.
- Loga `backtest_result` com métricas.
- Se `--output`, salva JSON com trades + equity + stats + metrics.

### Sizing (F5b)
- `_compute_volume(info, intent)`:
  - **FIXED_CONTRACTS:** `total_contracts * lot_per_contract` normalizado.
  - **BY_RISK:** `risk_money / loss_per_lot`.
  - `total_contracts` é **ignorado** em by-risk.
  - `risk_value=0` ou `sl_dist=0` → `lots_min` (fallback).

### Simulador (F2d + F5e)
- SL **ganha empate** dentro do mesmo tick (conservador, MT5-style).
- Parciais: **não implementadas no simulador ainda** (F5a cobriu `RealExecutor`).
- Volume = fixed_contracts (by-risk só em `RealExecutor`).
- **F5e:** `SimulatedExecutor.__init__(preset, slippage_points=0.0, spread_points=0.0)`. Slippage aplicado no fill (pior caso). `spread_points` reservado para F8+.

### `FakeGateway.place_order` — `is_stop` explícito (F5e)
- **Não** detecta mais por string. Usa `req.is_stop`.
- `is_stop=True` → registra ordem pendente (não abre posição).

### Interface Web (F7)
- **Stack:** FastAPI + Jinja2 + HTMX + Pico CSS + uPlot + SSE (F7f).
- **Sem build step.** Sem Node.js. Bundle < 200 KB.
- **Partial pattern:** templates começam com `_` (`_backtest.html`) ou são páginas (`backtest.html`).
- **Regra:** o `app.py` chama `TemplateResponse` com a página; o router chama com o partial.
- **HTMX JSON:** formulários com `hx-ext="json-enc"` (config).
- **HTMX multipart:** formulários de upload com `hx-encoding="multipart/form-data"` (backtest).
- **Read-only:** `/shadow` (F7e) **só compara**, não coloca ordens (usa `ShadowComparer`, não `RealExecutor`).

---

## 5. Próximos passos (F7f / F7g / F8+)

O projeto **F0→F6 + F7a→F7e está 100% completo**. Próximas fases:

### F7f — SSE (status em tempo real) — 2h

**O que implementa:** `GET /stream` (SSE) + dashboard consumindo com `hx-ext="sse"`.

**Arquivos:**
- `src/engine/web/routes/stream.py` — `StreamingResponse(media_type="text/event-stream")`.
- `src/engine/web/templates/dashboard.html` — `hx-ext="sse" sse-connect="/stream"`.
- `tests/test_web.py` — teste de conexão SSE.

**Critério:** dashboard atualiza sozinho a cada 2s (sem refresh manual).

### F7g — Testes web (~10-15 testes)

**O que implementa:** cobertura completa das rotas (`GET /`, `/config`, `/backtest`, `/shadow`, `POST /api/*`).

**Arquivos:**
- `tests/test_web.py` — casos de borda.

**Critério:** `uv run pytest -q` → ~240 passed.

### F8 — Parciais/reforço no simulador (3-4 dias)

**O que implementa:** o `SimulatedExecutor` (F2d) **não** simula parciais/reforço. Hoje:
- Parciais são armadas no MT5 real (`RealExecutor.place_partial_orders`), mas o simulador só vê SL/TP final.
- Reforço idem.

**Para paridade total em backtest**, o `SimulatedExecutor` precisa implementar:
- Fill de parcial quando `bid/ask` atinge o alvo do tier.
- Fill de reforço quando preço avança `reentry_arm_points` e volta ao entry.
- TP/SL do reforço separados.

**Arquivos:**
- `src/engine/application/simulation.py` — estender `_OpenTrade` com `partials` e `reentry`.
- `tests/test_simulation.py` — +5 testes.

### F9 — Estratégias adicionais

**O que implementa:** mais estratégias além de `stddev_v510`.

**Arquivos:**
- `presets/outra_estrategia.yaml` — novo preset.
- `src/engine/config/presets.py` — talvez outro `Preset` (não só `StdDevV510Preset`).
- `src/engine/cli.py` — `engine run --strategies=stddev_v510,outra`.
- `tests/test_*.py` — testes da nova estratégia.

### F10 — Multi-símbolo

**O que implementa:** rodar em N símbolos (WIN$N, WDO$N, etc).

**Hoje:** o `TradingSession` e o `RealExecutor` assumem **1 símbolo**. Precisa refatorar para receber `symbol` no `__init__` (ou N sessões, uma por símbolo).

### F11 — Observabilidade

**O que implementa:** métricas de produção (Prometheus, Grafana, etc).
- Hoje o motor só loga (structlog). Falta exportar métricas.

---

## 6. Comandos úteis

```powershell
# Testes
uv run pytest -q                              # suíte completa (231 passed hoje)
uv run pytest tests/test_golden_v510.py -v    # paridade do detector
uv run pytest tests/test_calendar.py -v       # calendário B3
uv run pytest tests/test_state.py -v          # persistência + parciais/reforço
uv run pytest tests/test_run.py -v            # engine run
uv run pytest tests/test_shadow.py -v         # modo sombra
uv run pytest tests/test_partials.py -v       # parciais
uv run pytest tests/test_reentry.py -v        # reforço
uv run pytest tests/test_registry.py -v       # multi-estratégia
uv run pytest tests/test_csv_loader.py -v     # CSV loader (F6)
uv run pytest tests/test_metrics.py -v        # métricas (F6)
uv run pytest tests/test_backtester.py -v     # Backtester (F6)
uv run pytest tests/test_web.py -v            # FastAPI web (F7a-F7e)

# Frontend
uv run uvicorn engine.web.app:app --reload --port 8000

# CLI
uv run engine version
uv run engine check-config                    # audita o preset (7 seções)
uv run engine status --fake                   # detector + gateway sintético
uv run engine status                          # detector + gateway real (MT5 aberto)
uv run engine run --dry-run --fast --max-ticks 10   # loop de teste (não conecta MT5)
uv run engine run --dry-run --fast --max-ticks 3 --strategies=stddev_v510  # multi-estratégia
uv run engine run --demo --db engine.db       # loop real em demo (MT5 aberto)
uv run engine shadow --ea-magic 20260718 --duration 60   # modo sombra
uv run engine backtest --csv tests/fixtures/sample_bars.csv   # backtest (F6)
uv run engine backtest --csv PATH --output result.json        # backtest com JSON

# Git
git add -A
git commit -m "feat(F7e): shadow web (231 passed)"
7. Como o próximo agente deve começar
Passo 1 — Confirmar estado atual:

powershell
uv run pytest -q
Deve mostrar 231 passed. Se não, PARE e investigue o que quebrou.

Passo 2 — Ler este AI.md inteiro. Principalmente seções 4 (decisões) e
5 (próximos passos F7f+). Para frontend, leia o ai_front_end.md.

Passo 3 — Rodar uv run engine check-config para confirmar que o preset
carrega (7 seções no log).

Passo 4 — Rodar uv run engine backtest --csv tests/fixtures/sample_bars.csv
para confirmar que o backtester funciona.

Passo 5 — Subir o frontend:

powershell
uv run uvicorn engine.web.app:app --reload --port 8000
Abra http://localhost:8000 → dashboard deve carregar.
Abra http://localhost:8000/backtest → form deve carregar.
Abra http://localhost:8000/shadow → aviso vermelho + form devem carregar.

Passo 6 — Se algo quebrar:

Rodar uv run pytest -q -x (para no primeiro erro)

Comparar com test_golden_v510.py se for detector, com test_regions.py se
for região, com test_presets.py se for config, com test_web.py se for frontend.

NÃO consertar teste quebrando código de produção. Se um teste antigo
quebrou, é bug novo, não do teste.

8. Bugs conhecidos / pontos de atenção
Bug cosmético — breakout logado 2×
Cada teste que chama _build_intent() ou _mk_sessao_com_regiao() loga breakout
2×. Não é bug, é o teste chamando helpers 2×. Cosmético.

session_shift usa TradingWindow(start=time(0,0), end=time(0,0))
Gambiarra para não precisar mudar a assinatura. TODO F8+: transformar em @staticmethod.

SimulatedExecutor não implementa parciais/reforço
Só SL/TP final. TODO F8.

SimulatedExecutor implementa slippage (F5e), mas não spread
spread_points é aceito, mas não aplicado (o ask/bid já contém spread). TODO F8+.

StrategyRegistry registra 1 estratégia com magic=0
Hoje só tem 1 preset. Se registrar 2, precisa magic diferente. TODO F9.

TradeIntent.volume = 0.0 antes do Executor
O TradingSession não calcula volume (precisa de SymbolInfo). O
Executor preenche. Não é bug, é decisão de design.

OrderResult.is_ok (não ok)
O OrderResult tem @property is_ok. Sempre use .is_ok em testes e código.

mute_open_min usa session.window.start
O EA usa InpStartHour (não a abertura real do pregão). Alinhado com EA.

Datas naive vs aware
O FakeGateway.history_deals normaliza since naive → aware UTC. O
RealMT5Gateway.history_deals também.

engine run no --dry-run cria engine.db
O cmd_run usa SqliteStateStore(args.db or "engine.db") inclusive em
--dry-run. O teste test_run_dry_run_max_ticks resolve isso passando
db=":memory:" e fazendo monkeypatch do SqliteStateStore.

TickInfo e symbol_info_tick (F3d)
TickInfo é um dataclass frozen com ask, bid, time (aware UTC).

engine shadow coloca ordens reais
Não é read-only. Use conta demo para testar. A rota web /shadow (F7e) NÃO coloca ordens (usa ShadowComparer read-only).

ShadowComparer não é idempotente
Cada chamada a compare() gera um ShadowReport novo.

Parciais: place_partial_orders chama symbol_info de novo
Não é bug, é decisão de design.

_infer_tier_from_comment depende do comment engine_partial_N
Se o Executor mudar o formato do comment, os dois quebram juntos.

Reforço: place_reentry_exits usa comment="engine_reentry_sl" e is_stop=True
O FakeGateway usa is_stop (F5e).

Multi-estratégia: --strategies e preset.strategy
O cmd_run registra o preset principal com name = preset.strategy.

--strategies=A,B usa preset.strategy. TODO F9: aceitar preset.name também.

Backtester — aproximação de ticks
Como o CSV só tem candles, o Backtester gera 2 ticks por candle (open e close).

Não simula o caminho intra-candle (o candle pode ter tocado SL/TP em qualquer ponto entre open e close).

TODO F8: parciais/reforço no simulador melhoram isso.

Backtester — parciais/reforço não são simulados
O SimulatedExecutor só tem SL/TP final.

TODO F8.

engine backtest — sem trades no fixture
tests/fixtures/sample_bars.csv tem 10 candles. O detector precisa de 180 para o z-score. Portanto, 0 trades. Para ver trades, use um CSV com 200+ candles.

Frontend (F7) — Bugs resolvidos e pontos de atenção
TemplateNotFound: partials começam com _ (_backtest.html), páginas não (backtest.html). O app.py pede a página; o router pede o partial.

TemplateResponse: TemplateResponse(request=request, name="...", context={...}) (Starlette ≥ 0.30). O request é obrigatório.

Código de teste no app.py: remover test_* do app.py (só em tests/test_web.py).

HTMX upload: hx-encoding="multipart/form-data" é obrigatório.

HTMX JSON: hx-ext="json-enc" para formulários de config.

TradeIntent no routes/shadow.py: usar _ShadowTrade (duck typing) em vez de TradeIntent inteiro.

SSE (F7f): StreamingResponse(media_type="text/event-stream") é obrigatório.

TestClient: with TestClient(app) as client: dispara o lifespan.

9. Referências externas
EA de referência: StdDevVolumeBreakout.mq5 v4.60 (Renan) — não está
no repositório, mas é a fonte de verdade. Se precisar comparar, pedir ao autor.

Indicador companheiro: VolumeStdBarPainter.mq5 v3.00 (multi-nível) e
v1.00 (simples).

Script golden: z_dump.mq5 — exporta candles + z-score para CSV
(usado para gerar tests/fixtures/v510_expected.csv).

Plano completo: Plano_Motor_Trading_Python.md (se existir no repo).

README: README.md na raiz (documenta estado atual + roadmap).

Frontend: ai_front_end.md (FastAPI, HTMX, templates, SSE).

10. Regras de ouro (para a IA que continuar)
Rode uv run pytest -q antes e depois de CADA mudança. Se quebrar,
reverta imediatamente. (Hoje: 231 passed.)

Nunca substitua arquivo inteiro sem antes dar uma olhada na versão atual.
O problema mais comum no histórico do projeto foi colar código novo em cima
do antigo sem remover, gerando SyntaxError (ex: from __future__ no
meio do arquivo, def duplicado na mesma linha).

Prefira Substituir em vez de Colar em cima quando eu mandar um
patch de arquivo.

Não mexa em domain/ sem rodar test_golden_v510.py + test_regions.py.
Esses dois são a fundação.

Não invente campos no preset sem consultar o .mq5. Cada campo tem um
# InpXxx correspondente.

Sempre use OrderResult.is_ok (não .ok).

Sempre rode uv run engine check-config depois de mexer no YAML.

Quando em dúvida, pergunte. O autor tem contexto do EA e sabe quando
uma mudança quebra paridade.

ExecutionResult.ok é alias de is_ok — mantenha as duas properties.

Datas: sempre aware UTC nos métodos públicos. Normalize since naive
para aware antes de comparar.

engine shadow coloca ordens reais. Só rode em demo até validar.

ShadowComparer não acessa MT5. Só engine shadow acessa. A rota web
/shadow também acessa (read-only).

Parciais no Poller: o comment do Executor é engine_partial_N. Se
mudar, o Poller e o TradingSession quebram juntos.

Reforço no Poller: o comment do Executor é engine_reentry (entrada)
e engine_reentry_tp/engine_reentry_sl (saídas). O is_stop do OrderRequest
é True no SL.

Calendário B3: B3Calendar tem feriados hardcoded 2026-2027. Se rodar
em 2028+, adicione à lista.

session_shift: usa TradingWindow(start=time(0,0), end=time(0,0)) —
gambiarra. F8+ transforma em @staticmethod.

Multi-estratégia: --strategies usa preset.strategy (não preset.name).

Frontend: para detalhes de HTMX, templates, rotas e SSE, leia o
ai_front_end.md. O app.py e os routers nunca duplicam lógica do
backend — só chamam engine.application.*.

F0→F6 + F7a→F7e está 100% completo. Próximas fases: F7f (SSE),
F7g (testes web), F8 (parciais/reforço no simulador), F9 (estratégias
adicionais), F10 (multi-símbolo), F11 (observabilidade).