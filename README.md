# Trading Engine — Motor Multi-Estratégia

Porte da estratégia **StdDevVolumeBreakout v4.60** para Python (API oficial
MetaTrader5), arquitetado em DDD/bounded contexts para múltiplas estratégias
plugáveis. Plano completo: `Plano_Motor_Trading_Python.md`.

**Estado atual:** **F0 → F6 + F7a → F7f concluídos.** O motor **detecta**
sinais (paridade bit-a-bit com o EA), **gerencia** regiões, **orquestra**
sessão, **simula** trades, **executa** ordens (real + fake), **reage** a
fills/SL/TP, **persiste** estado em SQLite, **roda em loop** real, **compara**
decisões com o EA em tempo real (modo sombra), **opera com parciais**
(tiers 1/2/3) com breakeven após Tier 1, **opera com reforço** no retorno à
entrada, **gerencia validade de regiões por pregões reais** (calendário B3),
**suporta slippage/spread no simulador**, **suporta multi-estratégia** (N sessões
por tick), **roda backtest próprio** (sem MT5, com métricas), e tem **frontend
web** completo (FastAPI + HTMX + Pico + uPlot) com **dashboard** (status em tempo real via SSE + equity + trades), **config** (edição de preset), **backtest** (upload CSV e resultado) e **shadow** (comparação read-only com o EA).
**F7g (testes de cobertura do frontend) é o próximo passo.**

---

## Setup (Windows — máquina/VPS de produção)

```powershell
# 1. Instalar uv (uma vez):  https://docs.astral.sh/uv/
# 2. No diretório do projeto:
uv venv
uv pip install -e ".[mt5,dev,web]"
copy .env.example .env      # e preencha login/senha/servidor/símbolo

# 3. Rodar
uv run engine version
uv run engine check-config        # audita TODAS as 7 seções do preset
uv run engine status              # conecta no terminal MT5 aberto
uv run engine status --fake       # sem MT5 (gateway sintético p/ desenvolvimento)
uv run engine run --dry-run --fast --max-ticks 10   # loop de teste sem MT5
uv run engine run --demo --db engine_demo.db        # loop real em demo
uv run engine shadow --ea-magic 20260718 --duration 60   # modo sombra
uv run engine backtest --csv tests/fixtures/sample_bars.csv   # backtest
uv run uvicorn engine.web.app:app --reload --port 8000   # frontend
uv run pytest -q                  # suíte completa (~232 testes)
Linux/macOS (desenvolvimento sem MT5): uv pip install -e ".[dev]" e usar --fake.

Frontend: abra http://localhost:8000 no navegador (com o uvicorn rodando).

Estrutura atual
text
src/engine/
├── domain/                          # PURO: zero imports externos
│   ├── shared/types.py              # Bar, Side, VolumeSource, MarketSnapshot
│   ├── risk/
│   │   ├── calendar.py              # TradingWindow (+ session_shift)
│   │   └── exchange_calendar.py     # B3Calendar (feriados 2026-2027) — F5d
│   ├── state/store.py               # StateStore (Protocol) + SessionSnapshot (F3c + F5e)
│   │                                #   + TradeRecord (F7b-1)
│   └── strategy/
│       ├── detector.py              # VolumeStdDetector (paridade bit-a-bit EA)
│       ├── location.py              # TradeLocation, RegionState, RegionPhase, RegisterResult
│       ├── regions.py               # RegionManager (governança, TTL, validade, rearme)
│       ├── pricing.py               # entry_level / stop_level / take_profit_level
│       │                            #   + PricingConfig + Enums de modo
│       └── strategy.py              # StrategyConfig (F5f)
│
├── config/
│   ├── settings.py                  # pydantic-settings (.env) + MT5Settings
│   └── presets.py                   # StdDevV510Preset (7 seções + validadores cruzados)
│
├── application/                     # orquestração (sem MT5, sem ordens)
│   ├── status.py                    # get_status (F0/F1)
│   ├── intent.py                    # TradeIntent, ReentryIntent, TickDecision, BarResult
│   ├── trading_session.py           # TradingSession (+ state_store + on_trade_event +
│   │                                #   calendar + persistência de parciais/reforço +
│   │                                #   save_trade em F7b-1)
│   ├── events.py                    # EventFeed, BarEvent, TickEvent (F2d)
│   ├── simulation.py                # run_simulation, SimulatedExecutor + slippage/spread (F5e)
│   ├── trade_events.py              # EntryFilled, PartialFilled, ReentryFilled,
│   │                                #   ReentryExitFilled, StopLossHit,
│   │                                #   TakeProfitHit, PositionClosed (F3b + F5c)
│   ├── poller.py                    # TradeEventPoller (F3b + F5c)
│   ├── executor.py                  # RealExecutor (+ close_all_at_end_of_day +
│   │                                #   place_partial_orders + place_reentry_* +
│   │                                #   by-risk sizing + is_stop)
│   ├── shadow_report.py             # ShadowReport + Divergence (F4)
│   ├── shadow.py                    # ShadowComparer (F4)
│   ├── partial_spec.py              # PartialSpec + make_partial_specs (F5a)
│   ├── registry.py                  # StrategyRegistry (F5f)
│   ├── metrics.py                   # Sharpe, drawdown, win rate, etc (F6)
│   └── backtester.py                # Backtester + BacktestResult (F6)
│
├── infrastructure/                  # ACL MetaTrader5 + persistência + CSV
│   ├── mt5/
│   │   ├── gateway.py               # BrokerGateway (Protocol) + RealMT5Gateway
│   │   └── fake.py                  # FakeGateway (determinístico, qualquer SO)
│   ├── logging/setup.py             # structlog (console / JSON)
│   ├── state/
│   │   ├── memory_store.py          # InMemoryStateStore (F7b-1: + save_trade)
│   │   └── sqlite_store.py          # SqliteStateStore (F7b-1: + tabela trades)
│   └── data/
│       └── csv_loader.py            # load_bars_csv (F6)
│
├── web/                             # Frontend (F7a+)
│   ├── __init__.py
│   ├── app.py                       # FastAPI app + rotas (F7a + F7c + F7d + F7e + F7f)
│   ├── deps.py                      # dependências (gateway, settings) (F7a)
│   ├── schemas.py                   # Pydantic (request/response)
│   ├── routes/
│   │   ├── trades.py                # GET /api/trades (F7b-2)
│   │   ├── equity.py                # GET /api/equity (F7b-2)
│   │   ├── preset.py                # GET/POST /api/preset (F7c)
│   │   ├── backtest.py              # GET/POST /api/backtest (F7d)
│   │   ├── shadow.py                # GET/POST /api/shadow (F7e)
│   │   └── stream.py                # GET /stream (SSE) (F7f)
│   ├── templates/
│   │   ├── base.html                # layout + HTMX + Pico + uPlot + json-enc + sse
│   │   ├── dashboard.html           # página principal (F7a + F7b-2 + F7f)
│   │   ├── _status.html             # partial (status p/ polling antigo) (F7a)
│   │   ├── _status_sse.html         # partial (status via SSE) (F7f)
│   │   ├── _trades.html             # partial (trades) (F7b-2)
│   │   ├── _equity.html             # partial (equity, uPlot) (F7b-2)
│   │   ├── config.html              # página de config (F7c)
│   │   ├── _preset.html             # partial (formulário, 7 blocos) (F7c)
│   │   ├── backtest.html            # página de backtest (F7d)
│   │   ├── _backtest.html           # partial (form + resultado) (F7d)
│   │   ├── shadow.html              # página de shadow (F7e)
│   │   └── _shadow.html             # partial (form + resultado) (F7e)
│   └── static/
│       ├── htmx.min.js              # 48 KB
│       ├── pico.min.css             # 83 KB
│       ├── uplot.min.js             # 50 KB
│       ├── uplot.min.css            # 1.9 KB
│       └── sse.js                   # 10 KB (F7f)
│
└── cli.py                           # engine status | check-config | run | shadow |
                                     #   backtest | version
presets/
└── stddev_v510_default.yaml         # todos os inputs do EA v4.60 comentados
tests/
├── fixtures/
│   ├── v510_expected.csv            # 679 candles WIN$N M1 + z-score do MT5
│   └── sample_bars.csv              # 10 candles (F6)
├── test_calendar.py                 # TradingWindow + B3Calendar + session_shift (F5d)
├── test_detector.py
├── test_presets.py
├── test_golden_v510.py              # paridade bit-a-bit vs EA v4.60
├── test_regions.py                  # RegionManager + validade por pregões reais
├── test_pricing.py
├── test_trading_session.py
├── test_simulation.py               # simulador + slippage/spread (F5e)
├── test_executor.py                 # executor + by-risk (F5b) + is_stop (F5e)
├── test_poller.py                   # TradeEventPoller (+ reentry em F5c)
├── test_state.py                    # StateStore + persistência (F5e + F7b-1 trades)
├── test_run.py
├── test_shadow.py                   # modo sombra
├── test_partials.py                 # parciais + integração (F5a)
├── test_reentry.py                  # reforço (F5c)
├── test_registry.py                 # StrategyRegistry (F5f)
├── test_csv_loader.py               # load_bars_csv (F6)
├── test_metrics.py                  # métricas (F6)
├── test_backtester.py               # Backtester (F6)
└── test_web.py                      # 17 testes (F7b-2 + F7c + F7d + F7e + F7f)
Fases concluídas
F0 ✔ — Esqueleto
CLI (engine status | check-config | version)

EngineSettings (pydantic-settings, prefixo ENGINE_, nested __)

BrokerGateway (Protocol) + RealMT5Gateway (import tardio) + FakeGateway

Logging estruturado (structlog: console legível ou JSON)

Empacotamento src/ layout, entry point engine = engine.cli:main

F1 ✔ — Paridade do detector com EA v4.60
Paridade bit-a-bit confirmada em 500 candles reais do WIN$N M1

Fixture golden gerado pelo script z_dump.mq5 rodado no MT5 (679 candles)

Semântica travada: janela inclui o candle avaliado, desvio amostral (n−1),
fonte TICK, candle em formação excluído

F2a ✔ — Preset completo
7 seções em StdDevV510Preset: detector, session, entry, stop,
take_profit, risk, regions

Validadores cruzados replicam o OnInit() do EA

presets/stddev_v510_default.yaml mapeia cada valor ao input MQL5

engine check-config audita todas as 7 seções

F2b ✔ — RegionManager + pricing
TradeLocation (fato imutável) + RegionState (estado mutável) + RegionPhase (enum)

RegionManager: registro, rompimento, governança, TTL, validade, rearme

pricing.py: 5 modos de entrada, 3 modos de SL, TP, regra de candle grande

CandidateMode: HIGHEST_VOLUME (default) e FIRST_READY

F2c ✔ — TradingSession
Orquestrador de decisão (sem ordens, sem MT5)

on_bar_closed(bar, zscore, now) — filtro mute_open_min + registro de região

on_tick(snapshot) — rompimento, TTL, filtros de sessão, TradeIntent

Filtros: horário operacional, entry block, cooldown pós-SL, limite diário,
carry delay, mute_open_min

F2d ✔ — Simulador (F6-lite)
EventFeed (BarEvent | TickEvent) em ordem cronológica

SimulatedExecutor: fill de limite quando bid <= entry (compra) /
ask >= entry (venda); SL ganha empate dentro do mesmo tick

run_simulation(feed, preset) → SimulationResult (trades + equity + stats)

F3a ✔ — RealExecutor + BrokerGateway expandido
BrokerGateway expandido: place_order, cancel_order, modify_position,
close_position, positions, orders, history_deals

RealExecutor: calcula volume, chama place_order, retorna ExecutionResult

F3b ✔ — TradeEventPoller + notificações
TradeEventPoller: lê history_deals, classifica em 5 tipos

TradingSession.on_trade_event: reage (cooldown, rearme, consume)

F3c ✔ — Persistência SQLite
StateStore (Protocol) + SessionSnapshot (dataclass frozen)

InMemoryStateStore + SqliteStateStore (schema auto-criado)

F3d ✔ — engine run (loop real + demo)
Subcomando engine run com --dry-run, --demo, --db, --poll-interval,
--max-ticks, --fast

TickInfo + symbol_info_tick(symbol)

F4 ✔ — Modo sombra
ShadowReport + Divergence

ShadowComparer.compare: match por (bar_time, is_buy, entry_price ± tolerance)

Relatório JSON em reports/shadow_YYYYMMDD_HHMMSS.json

F5a ✔ — Parciais (tiers 1/2/3)
PartialSpec + make_partial_specs

RealExecutor.place_partial_orders(intent, symbol)

Breakeven após Tier 1

F5b ✔ — By-risk sizing
_compute_volume com SizingMode.BY_RISK (fixed_money / percent_balance)

F5c ✔ — Reforço no retorno à entrada
ReentryIntent emitida pelo TradingSession._maybe_reentry

executor.place_reentry_order + place_reentry_exits

F5d ✔ — Validade por pregões reais (calendário B3)
B3Calendar — feriados 2026-2027 hardcoded

TradingWindow.session_shift(bar_time, now, calendar)

F5e ✔ — Slippage/spread + correções pendentes
SimulatedExecutor(slippage_points, spread_points)

OrderRequest.is_stop: bool

TradingSession.calendar (B3Calendar por default)

SessionSnapshot persiste parciais/reforço

F5f ✔ — Multi-estratégia
StrategyConfig + StrategyRegistry

engine run --strategies=A,B (N sessões por tick)

F6 ✔ — Backtester próprio
load_bars_csv, metrics.py, Backtester.run(bars) → BacktestResult

engine backtest --csv PATH

F7a ✔ — Frontend setup + status
FastAPI + uvicorn + HTMX + Pico.css + Jinja2

GET / → dashboard (status)

GET /api/status → JSON/HTML (conta + detector)

F7b-1 ✔ — Tabela trades no SQLite
TradeRecord + save_trade/list_trades/list_equity

TradingSession._save_closed_trade (grava em SL/TP/close)

F7b-2 ✔ — Dashboard completo
GET /api/trades + GET /api/equity (JSON/HTML)

_trades.html + _equity.html (uPlot)

Dashboard com 3 seções (status + equity + trades)

F7c ✔ — Config (edição de preset)
GET /api/preset (JSON/HTML)

POST /api/preset (valida + backup .bak + salva YAML)

Página /config com formulário (7 blocos)

Plugin json-enc do HTMX

F7d ✔ — Backtest
GET /backtest (página com upload de CSV)

POST /api/backtest (roda Backtester e retorna métricas em HTML/JSON)

_backtest.html (formulário + card verde com resultado)

Multipart form (hx-encoding)

F7e ✔ — Shadow (read-only)
GET /shadow (página com aviso vermelho sobre read-only vs CLI)

POST /api/shadow (coleta deals do EA e do Python e usa ShadowComparer)

_shadow.html (formulário + card verde com Match Rate + tabela de divergências)

Uso de _ShadowTrade (duck typing) para evitar dependência de TradeIntent inteiro

F7f ✔ — SSE (status em tempo real)
GET /stream → StreamingResponse (text/event-stream)

Dashboard consome via hx-ext="sse" sse-connect="/stream" sse-swap="message"

Partial _status_sse.html renderizado no backend e empurrado via SSE

Loop encerra quando o cliente desconecta (Request.is_disconnected())

Decisões de arquitetura (registradas)
Tema	Decisão
Config	Pydantic 2 + pydantic-settings (.env); Pulumi adiado até deploy em nuvem
Backtest	.mq5 (Strategy Tester) ou engine backtest (F6)
Estado	SQLite em F3c (regiões + session_state), com schema auto-criado
Barramento	Interno síncrono; RabbitMQ só se distribuir (F8+)
Semântica detector	Idêntica ao EA (janela inclusiva, desvio amostral, fórmula de uma passada)
Sizing	Fixo (total_contracts * lot_per_contract) ou by-risk (fixed_money / % balance)
Modelo de execução	SL ganha empate no simulador (conservador, MT5-style)
RegionManager	dict mutável + enum de fase (evita flags impossíveis); MAX_LOC=12
Filtro de abertura	mute_open_min no TradingSession (não no RegionManager)
Volume REAL	Fallback REAL→TICK no domínio (defensável; WIN$N tem real_volume > 0)
Datas	Sempre aware UTC nos métodos públicos; normalizar since naive
Modo sombra	Magic do EA por parâmetro (não hardcoded); comparação por bar_time
Parciais (F5a)	comment=engine_partial_N; _infer_tier_from_comment extrai o N
Reforço (F5c)	comment=engine_reentry (entrada) e engine_reentry_tp/engine_reentry_sl (saídas)
Calendário B3 (F5d)	Feriados 2026-2027 hardcoded; atualizar uma vez por ano
Slippage (F5e)	SimulatedExecutor(slippage_points, spread_points); pior caso sempre
is_stop (F5e)	Campo explícito no OrderRequest (elimina detecção por string)
Multi-estratégia (F5f)	StrategyRegistry + engine run --strategies=A,B; N sessões por tick
Backtester (F6)	Backtester reusa SimulatedExecutor + EventFeed; 2 ticks por candle
Frontend (F7a)	FastAPI + HTMX + Pico + Jinja2; sem Node.js, sem build step
HTMX (F7a)	hx-swap="innerHTML"; negociação HTML/JSON via header HX-Request
Gráficos (F7b-2)	uPlot (50 KB) para equity curve
Trades no dashboard (F7b-1)	SQLite (engine.db, tabela trades); persiste sem MT5
Config (F7c)	Formulário com hx-ext="json-enc"; backup .bak antes de salvar
Backtest (F7d)	Multipart upload (hx-encoding); Backtester síncrono e read-only
Shadow (F7e)	Read-only (ShadowComparer); não coloca ordens; usa duck typing
SSE (F7f)	StreamingResponse + hx-ext="sse"; partial _status_sse.html
Roadmap
Fase	Descrição	Status
F0	Esqueleto (CLI, config, ACL, fake)	✔
F1	Paridade do detector com EA v4.60 (500 candles, tol=1e-9)	✔
F2a	Preset completo (7 seções) + validadores cruzados + YAML	✔
F2b	RegionManager + TradeLocation + pricing (5 modos entry, 3 SL)	✔
F2c	TradingSession (filtros de sessão + TradeIntent)	✔
F2d	Simulador (EventFeed + SimulatedExecutor + run_simulation)	✔
F3a	RealExecutor + BrokerGateway expandido	✔
F3b	TradeEventPoller + notificações	✔
F3c	Persistência SQLite	✔
F3d	engine run (loop real + demo)	✔
F4	Modo sombra (compara decisões com EA em tempo real)	✔
F5a	Parciais (tiers 1/2/3) + breakeven após Tier 1	✔
F5b	By-risk sizing (fixed_money + percent_balance)	✔
F5c	Reforço no retorno à entrada (use_reentry)	✔
F5d	Validade por pregões reais (calendário B3)	✔
F5e	Slippage/spread + is_stop + calendar + persistência	✔
F5f	Multi-estratégia (StrategyConfig + StrategyRegistry)	✔
F6	Backtester próprio (sem MT5, com métricas)	✔
F7a	Frontend setup + status (FastAPI + HTMX + Pico)	✔
F7b-1	Tabela trades no SQLite + gravação em on_trade_event	✔
F7b-2	Dashboard com equity curve (uPlot) + tabela de trades	✔
F7c	Config (edição de preset via formulário)	✔
F7d	Backtest (upload CSV + resultado)	✔
F7e	Shadow (rodar + resultado)	✔
F7f	SSE (status em tempo real no dashboard)	✔
F7g	Testes (cobertura completa do TestClient)	⏳ próximo
F8+	Validação em demo, parciais/reforço no simulador, multi-símbolo, observabilidade	⏳ opcional
Suíte de testes
powershell
uv run pytest -q                              # ~232 testes
uv run pytest -v                              # verbose
uv run pytest tests/test_golden_v510.py -v    # só paridade do detector
uv run pytest tests/test_calendar.py -v       # calendário B3 (F5d)
uv run pytest tests/test_state.py -v          # persistência (F5e + F7b-1)
uv run pytest tests/test_run.py -v            # engine run
uv run pytest tests/test_shadow.py -v         # modo sombra
uv run pytest tests/test_partials.py -v       # parciais (F5a)
uv run pytest tests/test_reentry.py -v        # reforço (F5c)
uv run pytest tests/test_registry.py -v       # multi-estratégia (F5f)
uv run pytest tests/test_csv_loader.py -v     # CSV loader (F6)
uv run pytest tests/test_metrics.py -v        # métricas (F6)
uv run pytest tests/test_backtester.py -v     # Backtester (F6)
uv run pytest tests/test_web.py -v            # frontend (F7b-2 a F7f)
Comandos úteis (CLI + Frontend)
powershell
# Backend (CLI)
uv run engine version                              # versão
uv run engine check-config                         # audita preset (7 seções)
uv run engine status --fake                        # detector + gateway sintético
uv run engine status                               # detector + gateway real (MT5)
uv run engine run --dry-run --fast --max-ticks 10  # loop de teste (sem MT5)
uv run engine run --dry-run --fast --max-ticks 3 --strategies=stddev_v510  # multi-estratégia
uv run engine run --demo --db engine_demo.db       # loop real em demo
uv run engine shadow --ea-magic 20260718 --duration 60   # modo sombra
uv run engine backtest --csv PATH                  # backtest (F6)

# Frontend
uv run uvicorn engine.web.app:app --reload --port 8000   # servidor web
# Abrir: http://localhost:8000          (dashboard, com SSE)
#        http://localhost:8000/config   (config)
#        http://localhost:8000/backtest (backtest)
#        http://localhost:8000/shadow   (shadow - read only)
Referências
EA de referência: StdDevVolumeBreakout.mq5 v4.60 (Renan)

Indicador companheiro: VolumeStdBarPainter.mq5 v3.00 (multi-nível) e v1.00 (simples)

Script golden: z_dump.mq5 (exporta candles + z-score para CSV)

Fixture real: tests/fixtures/v510_expected.csv (679 candles WIN$N M1, 29/10/2026)

Plano completo: Plano_Motor_Trading_Python.md

Guia único de retomada: AI.md (backend + frontend)

Manual de uso: MANUAL.md (passo a passo de operação)