📄 AI.md (Completo e Atualizado com F10)
markdown
# AI.md — Guia Único de Retomada do Projeto Trading Engine

> **Propósito deste arquivo:** permitir que uma IA (ou o autor) retome o projeto
> em outro chat/sessão **sem contexto anterior**, saiba **exatamente** onde
> paramos, o que falta, e o que **não pode ser quebrado**.
>
> **Leia este arquivo INTEIRO antes de escrever qualquer linha de código.**
> Ele evita retrabalho, decisões já tomadas e bugs conhecidos.
>
> **Este é o único guia do projeto (Backend + Frontend).** Ele substitui o
> antigo `ai_front_end.md` para ser a fonte única da verdade.

---

## 1. Contexto do projeto

Porte em Python do EA **`StdDevVolumeBreakout.mq5` v4.60** (MQL5) para a API
oficial **MetaTrader5** (pacote `MetaTrader5` pip, só Windows). Arquitetura
**hexagonal + DDD**, com domínio puro e ACL do MT5.

**Objetivo final:** motor multi-estratégia, hoje focado em UMA estratégia
(`stddev_v510`), com paridade bit-a-bit com o EA original, capaz de operar em
conta demo/real via MT5, comparar resultado com o Strategy Tester do MT5 e ter
uma interface web visual e leve.

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
12. **Interface Web (F7)** (FastAPI + HTMX + Pico CSS) para monitoramento, backtests, configuração e atualização em tempo real (SSE).
13. **Modo Armadilha (F9)** (inverte a direção do rompimento).
14. **Gráfico de Candles (F10)** (visualização dos trades em candles, com volume, timeframes e ferramenta de medição).

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
| **F7f** | Frontend: SSE (status em tempo real) | ✅ fechado |
| **F7g** | Frontend: Testes de cobertura (24 testes web) | ✅ fechado |
| **F8** | Simulador: Parciais e reforço no `SimulatedExecutor` | ✅ fechado |
| **F9** | Modo Armadilha (Trap): inverte a direção do rompimento | ✅ fechado |
| **F10** | Gráfico de Candles: visualização dos trades (volume, timeframes, medição) | ✅ fechado |
| **F11** | Multi-símbolo (`--symbols=WIN$N,WDO$N`) | ✅ fechado |
| **F12** | Observabilidade (Prometheus `/metrics`) | ✅ fechado |

**Suíte de testes atual:** **241 passed** (`uv run pytest -q`).
**Projeto completo (F0→F6 + F7a→F7g + F8 + F9 + F10).**

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
│ │ # + PricingConfig + Enums de modo + TrapMode (F9)
│ └── strategy.py # StrategyConfig (F5f)
│
├── config/
│ ├── settings.py # EngineSettings (pydantic-settings, .env)
│ └── presets.py # StdDevV510Preset (7 seções + validadores cruzados + F9)
│
├── application/ # orquestração (sem MT5, sem ordens)
│ ├── status.py # get_status (F0/F1)
│ ├── intent.py # TradeIntent, ReentryIntent, TickDecision, BarResult
│ ├── trading_session.py # TradingSession (+ state_store + on_trade_event +
│ │ # calendar + persistência + save_trade + F9)
│ ├── events.py # EventFeed, BarEvent, TickEvent (F2d)
│ ├── simulation.py # run_simulation, SimulatedExecutor
│ │ # + slippage/spread (F5e)
│ │ # + parciais/reforço (F8)
│ │ # + trap (F9)
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
│ ├── routes/ # Routers (trades, equity, preset, backtest, shadow, stream)
│ ├── templates/ # base.html, dashboard.html, partials _*.html
│ └── static/ # htmx, pico, uplot, sse, lightweight-charts
│
└── cli.py # engine status | check-config | run | shadow |

backtest | version
presets/
└── stddev_v510_default.yaml # todos os inputs do EA v4.60 comentados
tests/
├── fixtures/
│ ├── v510_expected.csv # 679 candles WIN$N M1 + z-score do MT5
│ ├── sample_bars.csv # 10 candles (F6)
│ └── WINZ26_M1_1_a_6_nov_26.csv # 6 dias de nov (novo)
├── test_calendar.py # TradingWindow + B3Calendar + session_shift (F5d)
├── test_detector.py
├── test_presets.py
├── test_golden_v510.py # paridade bit-a-bit vs EA v4.60
├── test_regions.py # RegionManager + validade por pregões reais
├── test_pricing.py
├── test_trading_session.py
├── test_simulation.py # simulador + slippage/spread (F5e) + parciais/reforço (F8)
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
└── test_web.py # TestClient FastAPI (F7a-F7g) — 24 testes

text

---

## 4. Decisões de arquitetura (NÃO MUDE SEM MOTIVO FORTE)

### Domínio puro (Backend)
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
- **F9:** no modo trap (`trigger_mode == "trap"`), a direção é invertida e o SL/TP são recalculados com a direção invertida.

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

### `Backtester` (F6 + F8 + F10)
- Consome `list[Bar]` (do `csv_loader`).
- Constrói `EventFeed`:
  - `BarEvent(bar, zscore)` para cada candle (z-score via `VolumeStdDetector`).
  - 2 `TickEvent` (open e close) para cada candle.
- Roda `run_simulation(feed, preset, ...)` → `SimulationResult`.
- **F8:** o `SimulatedExecutor` agora simula parciais e reforço, então o backtest reflete o comportamento real do MT5.
- **F10:** retorna JSON com `candles`, `volumes`, `markers` e `summary` para o frontend renderizar o gráfico.
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

### Simulador (F2d + F5e + F8 + F9)
- SL **ganha empate** dentro do mesmo tick (conservador, MT5-style).
- **F8:** Parciais e reforço implementados no `SimulatedExecutor`.
- **F9:** Modo trap implementado com `sim_pending_armed` e `is_trap`.
- Volume = fixed_contracts (by-risk só em `RealExecutor`).
- **F5e:** `SimulatedExecutor.__init__(preset, slippage_points=0.0, spread_points=0.0)`. Slippage aplicado no fill (pior caso).
- **F8:** `SimulatedExecutor._open` rastreia `partials_done`, `reentry_armed`, `reentry_done`. `on_tick` verifica os alvos dos tiers e o retorno ao entry.

### `FakeGateway.place_order` — `is_stop` explícito (F5e)
- **Não** detecta mais por string. Usa `req.is_stop`.
- `is_stop=True` → registra ordem pendente (não abre posição).

### Interface Web (F7 + F10)
- **Stack:** FastAPI + Jinja2 + HTMX + Pico CSS + uPlot + SSE (F7f) + Lightweight Charts (F10).
- **Sem build step.** Sem Node.js. Bundle < 250 KB.
- **Partial pattern:** templates começam com `_` (`_backtest.html`) ou são páginas (`backtest.html`).
- **Regra:** o `app.py` chama `TemplateResponse` com a página; o router chama com o partial.
- **HTMX JSON:** formulários com `hx-ext="json-enc"` (config).
- **HTMX multipart:** formulários de upload com `hx-encoding="multipart/form-data"` (backtest).
- **Read-only:** `/shadow` (F7e) **só compara**, não coloca ordens (usa `ShadowComparer`, não `RealExecutor`).
- **SSE:** `/stream` (F7f) usa `StreamingResponse` e HTMX `hx-ext="sse"`.
- **Gráfico de Candles (F10):** Lightweight Charts + volume + timeframes + ferramenta de medição (Shift + arrastar).

---

## 5. Próximos passos (F11+)

O projeto **F0→F6 + F7a→F7g + F8 + F9 + F10 + f11 + f12 está 100% completo**.

### F13 — Operação Real (validação em demo/real)

**O que implementa:** rodar o motor na conta demo/real por 1-2 semanas, comparar com o backtest e ajustar os parâmetros.
- **Isso é a fase mais crítica do projeto:** validar que a estratégia é lucrativa em condições reais de mercado.

---

## 6. Comandos úteis

```powershell
# Testes
uv run pytest -q                              # suíte completa (241 passed hoje)
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
uv run pytest tests/test_web.py -v            # FastAPI web (F7a-F7g)
uv run pytest tests/test_simulation.py -v     # simulador + F8 (parciais/reforço)

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
git commit -m "feat(F10): gráfico de candles (241 passed)"
7. Como o próximo agente deve começar
Passo 1 — Confirmar estado atual:

powershell
uv run pytest -q
Deve mostrar 241 passed. Se não, PARE e investigue o que quebrou.

Passo 2 — Ler este AI.md inteiro. Principalmente seções 4 (decisões) e
5 (próximos passos F11+).

Passo 3 — Rodar uv run engine check-config para confirmar que o preset
carrega (7 seções no log).

Passo 4 — Rodar uv run engine backtest --csv tests/fixtures/sample_bars.csv
para confirmar que o backtester funciona.

Passo 5 — Subir o frontend:

powershell
uv run uvicorn engine.web.app:app --reload --port 8000
Abra http://localhost:8000 → dashboard deve carregar (com SSE).
Abra http://localhost:8000/backtest → form deve carregar e o gráfico deve renderizar após o upload do CSV.
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

F8: parciais/reforço no simulador melhoram isso (agora os níveis de saída são respeitados dentro do candle).

engine backtest — sem trades no fixture
tests/fixtures/sample_bars.csv tem 10 candles. O detector precisa de 180 para o z-score. Portanto, 0 trades. Para ver trades, use um CSV com 200+ candles.

Frontend (F7) — Bugs resolvidos e pontos de atenção
TemplateNotFound: partials começam com _ (_backtest.html), páginas não (backtest.html). O app.py pede a página; o router pede o partial.

TemplateResponse: TemplateResponse(request=request, name="...", context={...}) (Starlette ≥ 0.30). O request é obrigatório.

Código de teste no app.py: remover test_* do app.py (só em tests/test_web.py).

HTMX upload: hx-encoding="multipart/form-data" é obrigatório.

HTMX JSON: hx-ext="json-enc" para formulários de config.

TradeIntent no routes/shadow.py: usar _ShadowTrade (duck typing) em vez de TradeIntent inteiro.

SSE (F7f): StreamingResponse(media_type="text/event-stream") é obrigatório. Se o uvicorn travar no Ctrl+C, feche a aba do navegador antes.

TestClient: with TestClient(app) as client: dispara o lifespan.

F9 (Modo Armadilha) — Pontos de atenção
trigger_mode é uma string ("trap" ou "normal"). A comparação deve ser feita com preset.trigger_mode == "trap" (não com o Enum).

_make_intent inverte is_buy e recalcula SL/TP com a direção invertida (usando stop_level e take_profit_level).

SimulatedExecutor.on_tick trata o reason == "trap" como ordem stop (preço precisa subir para vender, descer para comprar).

trap_arm_points muito grande (ex: 200) pode fazer o trade nunca abrir. Use valores menores (20-50) para calibrar.

F10 (Gráfico de Candles) — Pontos de atenção
lightweight-charts.js deve estar em static/: o arquivo deve ter ~160 KB. Se tiver 89 bytes, o download falhou.

base.html deve carregar o script: <script src="/static/lightweight-charts.js"></script>.

O gráfico só renderiza após o backtest: o endpoint /api/backtest/chart retorna os candles + markers.

Ferramenta de medição: Shift + arrastar para medir a distância em pontos. Duplo clique limpa.

Timeframes: 1M, 5M, 15M, 30M, 4H, D, M. A agregação é local (no JavaScript), sem chamadas extras ao backend.

9. Referências externas
EA de referência: StdDevVolumeBreakout.mq5 v4.60 (Renan) — não está
no repositório, mas é a fonte de verdade. Se precisar comparar, pedir ao autor.

Indicador companheiro: VolumeStdBarPainter.mq5 v3.00 (multi-nível) e
v1.00 (simples).

Script golden: z_dump.mq5 — exporta candles + z-score para CSV
(usado para gerar tests/fixtures/v510_expected.csv).

Plano completo: Plano_Motor_Trading_Python.md (se existir no repo).

README: README.md na raiz (documenta estado atual + roadmap).

Manual de uso: MANUAL.md (passo a passo de operação).

10. Regras de ouro (para a IA que continuar)
Rode uv run pytest -q antes e depois de CADA mudança. Se quebrar,
reverta imediatamente. (Hoje: 241 passed.)

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

Nunca duplique lógica do backend. O app.py e os routers da web
nunca reimplementam cálculo — só chamam engine.application.* e
engine.infrastructure.*.

Não exponha engine.db nem .env no navegador. O frontend só vê JSON
público (ou HTML via HTMX/SSE).

Formulários HTMX usam hx-ext="json-enc" (config) ou
hx-encoding="multipart/form-data" (upload). SSE usa hx-ext="sse".

TestClient precisa de with TestClient(app) as client: para disparar o
lifespan (startup/shutdown).

Backup de preset: o POST /api/preset copia o YAML atual para .bak
antes de salvar.

Padrão de template: partials começam com _ (_status.html,
_backtest.html, _shadow.html, _status_sse.html); páginas não
(dashboard.html, backtest.html, shadow.html).

Código de teste NUNCA no app.py. Sempre em tests/test_web.py.

SSE: o servidor segura a conexão. Se for parar o uvicorn, feche a aba
do navegador antes do Ctrl+C. O formato do frame é data: <linha>\n\n.

Modo trap: trigger_mode é string ("trap" ou "normal"). No modo trap, _make_intent inverte is_buy e recalcula SL/TP com stop_level e take_profit_level. O SimulatedExecutor.on_tick trata reason == "trap" como ordem stop.

F10: o gráfico de candles usa Lightweight Charts. O endpoint /api/backtest/chart retorna candles, volumes, markers e summary. A ferramenta de medição (Shift + arrastar) calcula a distância em pontos.

F0→F6 + F7a→F7g + F8 + F9 + F10 está 100% completo. Próximas fases: F11
(multi-símbolo), F12 (observabilidade), F13 (operação real).