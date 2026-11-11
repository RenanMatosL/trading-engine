# Trading Engine — Motor Multi-Estratégia

Porte da estratégia **StdDevVolumeBreakout v4.60** para Python (API oficial
MetaTrader5), arquitetado em DDD/bounded contexts para múltiplas estratégias
plugáveis. Plano completo: `Plano_Motor_Trading_Python.md`.

**Estado atual:** **F0 → F13 concluídos.** O motor **detecta** sinais (paridade
bit-a-bit com o EA), **gerencia** regiões, **orquestra** sessão, **simula**
trades, **executa** ordens (real + fake), **reage** a fills/SL/TP, **persiste**
estado em SQLite, **roda em loop** real, **compara** decisões com o EA em tempo
real (modo sombra), **opera com parciais** (tiers 1/2/3) com breakeven após
Tier 1, **opera com reforço** no retorno à entrada, **gerencia validade de
regiões por pregões reais** (calendário B3), **suporta slippage/spread no
simulador**, **suporta multi-estratégia** (N sessões por tick), **suporta
multi-símbolo** (`--symbols=WIN$N,WDO$N`), **roda backtest próprio** (sem MT5,
com métricas e gráfico de candles), tem **modo armadilha (trap)**, **frontend
web** completo (FastAPI + HTMX + Pico + uPlot + Lightweight Charts) com
**dashboard** (status SSE + gráfico de candles ao vivo + equity + trades),
**config** (edição de preset), **backtest** (upload CSV + resultado + gráfico com volume e timeframes) e
**shadow** (comparação read-only com o EA), **observabilidade** (métricas
Prometheus no endpoint `/metrics`), e **operação demo (F13)** com **trava anti-spam** 
(impede ordens duplicadas), **warm-up histórico** (puxa os 2 últimos dias e salva os 
gatilhos no banco) e **pintura de gatilhos no gráfico** (setas roxas sobre os candles).
**F14 (Correção de fuso horário) é o próximo passo.**

---

## Setup (Windows — máquina/VPS de produção)

```powershell
# 1. Instalar uv (uma vez):  https://docs.astral.sh/uv/
# 2. No diretório do projeto:
uv venv
uv pip install -e ".[mt5,dev,web]"
uv add tzdata               # F13: necessário para ZoneInfo no Windows
copy .env.example .env      # e preencha login/senha/servidor/símbolo

# 3. Rodar
uv run engine version
uv run engine check-config        # audita TODAS as 7 seções do preset
uv run engine status              # conecta no terminal MT5 aberto
uv run engine status --fake       # sem MT5 (gateway sintético p/ desenvolvimento)
uv run engine run --dry-run --fast --max-ticks 10   # loop de teste sem MT5
uv run engine run --demo --symbols=WINZ26 > logs_demo.txt 2>&1  # operação demo
uv run engine run --demo --symbols=WIN$N,WDO$N      # multi-símbolo
uv run engine shadow --ea-magic 20260718 --duration 60   # modo sombra
uv run engine backtest --csv tests/fixtures/sample_bars.csv   # backtest
uv run uvicorn engine.web.app:app --reload --port 8000   # frontend
uv run pytest -q                  # suíte completa (~241 testes)
Linux/macOS (desenvolvimento sem MT5): uv pip install -e ".[dev]" e usar --fake.

Frontend: abra http://localhost:8000 no navegador (com o uvicorn rodando).
Observabilidade: acesse http://localhost:8000/metrics (formato Prometheus).
Estrutura atual
text
src/engine/
├── domain/                          # PURO: zero imports externos
│   ├── shared/types.py              # Bar, Side, VolumeSource, MarketSnapshot
│   ├── risk/
│   │   ├── calendar.py              # TradingWindow (+ session_shift)
│   │   └── exchange_calendar.py     # B3Calendar (feriados 2026-2027) — F5d
│   ├── state/store.py               # StateStore (Protocol) + SessionSnapshot + TradeRecord
│   └── strategy/
│       ├── detector.py              # VolumeStdDetector (paridade bit-a-bit EA)
│       ├── location.py              # TradeLocation, RegionState, RegionPhase
│       ├── regions.py               # RegionManager (governança, TTL, validade, rearme)
│       ├── pricing.py               # entry_level / stop_level / take_profit_level
│       │                            #   + PricingConfig + TrapMode (F9)
│       └── strategy.py              # StrategyConfig (F5f)
│
├── config/
│   ├── settings.py                  # pydantic-settings (.env) + MT5Settings
│   └── presets.py                   # StdDevV510Preset (7 seções + validadores + F9)
│
├── application/                     # orquestração (sem MT5, sem ordens)
│   ├── status.py                    # get_status (F0/F1)
│   ├── intent.py                    # TradeIntent, ReentryIntent, TickDecision, BarResult
│   ├── trading_session.py           # TradingSession (+ TRAVA ANTI-SPAM em _make_intent, F13)
│   ├── events.py                    # EventFeed, BarEvent, TickEvent (F2d)
│   ├── simulation.py                # run_simulation, SimulatedExecutor
│   │                                #   + slippage/spread (F5e) + parciais/reforço (F8)
│   ├── trade_events.py              # EntryFilled, PartialFilled, ReentryFilled, etc (F3b + F5c)
│   ├── poller.py                    # TradeEventPoller (F3b + F5c)
│   ├── executor.py                  # RealExecutor (+ parciais/reforço + is_stop + by-risk)
│   ├── shadow_report.py             # ShadowReport + Divergence (F4)
│   ├── shadow.py                    # ShadowComparer (F4)
│   ├── partial_spec.py              # PartialSpec + make_partial_specs (F5a)
│   ├── registry.py                  # StrategyRegistry (F5f)
│   ├── metrics_exporter.py          # Métricas Prometheus (F12)
│   ├── metrics.py                   # Sharpe, drawdown, win rate, etc (F6)
│   └── backtester.py                # Backtester + BacktestResult (F6)
│
├── infrastructure/                  # ACL MetaTrader5 + persistência + CSV
│   ├── mt5/
│   │   ├── gateway.py               # BrokerGateway (Protocol) + RealMT5Gateway
│   │   │                            #   + F13: ORDER_TIME_DAY (correção expiração)
│   │   └── fake.py                  # FakeGateway (determinístico)
│   ├── logging/setup.py             # structlog (console / JSON)
│   ├── state/
│   │   ├── memory_store.py          # InMemoryStateStore (F7b-1)
│   │   └── sqlite_store.py          # SqliteStateStore (F7b-1)
│   └── data/
│       └── csv_loader.py            # load_bars_csv (F6)
│
├── web/                             # Frontend (F7a+)
│   ├── app.py                       # FastAPI app + rotas (F7a-F12)
│   ├── deps.py                      # gateway, settings
│   ├── schemas.py                   # Pydantic schemas
│   ├── routes/
│   │   ├── trades.py                # F13: /api/trades, /api/history_markers, /api/candles
│   │   ├── equity.py                # GET /api/equity
│   │   ├── preset.py                # GET/POST /api/preset
│   │   ├── backtest.py              # GET/POST /api/backtest + /api/backtest/chart
│   │   ├── shadow.py                # GET/POST /api/shadow
│   │   ├── stream.py                # F13: GET /stream (SSE JSON)
│   │   └── metrics.py               # GET /metrics (Prometheus) — F12
│   ├── templates/
│   │   ├── base.html                # layout + HTMX + Pico + uPlot + json-enc + sse + lightweight-charts
│   │   ├── dashboard.html           # F13: Dashboard com gráfico em tempo real e tabela de status
│   │   ├── _status.html             # partial (status)
│   │   ├── _status_sse.html         # partial (status via SSE)
│   │   ├── _trades.html             # partial (trades, com horário formatado)
│   │   ├── _equity.html             # partial (equity, uPlot)
│   │   ├── config.html              # página de config
│   │   ├── _preset.html             # partial (formulário, 7+ blocos)
│   │   ├── backtest.html            # página de backtest (F7d + F10)
│   │   ├── _backtest.html           # partial (form + resultado)
│   │   ├── shadow.html              # página de shadow
│   │   └── _shadow.html             # partial (form + resultado)
│   └── static/
│       ├── htmx.min.js              # 48 KB
│       ├── pico.min.css             # 83 KB
│       ├── uplot.min.js             # 50 KB
│       ├── uplot.min.css            # 1.9 KB
│       ├── sse.js                   # 10 KB
│       └── lightweight-charts.js    # 160 KB (F10)
│
└── cli.py                           # engine status | check-config | run | shadow |
                                     #   backtest | version
                                     # F13: _warmup_historico, _save_trigger_candle

presets/
└── stddev_v510_default.yaml         # todos os inputs do EA v4.60 comentados

tests/
├── fixtures/
│   ├── v510_expected.csv            # 679 candles WIN$N M1 + z-score do MT5
│   ├── sample_bars.csv              # 10 candles
│   └── WINZ26_M1_1_a_6_nov_26.csv   # 6 dias de nov
├── test_calendar.py                 # TradingWindow + B3Calendar
├── test_detector.py
├── test_presets.py
├── test_golden_v510.py              # paridade bit-a-bit vs EA v4.60
├── test_regions.py                  # RegionManager + validade por pregões reais
├── test_pricing.py
├── test_trading_session.py
├── test_simulation.py               # simulador + slippage/spread
├── test_executor.py                 # executor + by-risk + is_stop
├── test_poller.py                   # TradeEventPoller
├── test_state.py                    # StateStore + persistência
├── test_run.py
├── test_shadow.py                   # modo sombra
├── test_partials.py                 # parciais + integração
├── test_reentry.py                  # reforço
├── test_registry.py                 # StrategyRegistry
├── test_csv_loader.py               # load_bars_csv
├── test_metrics.py                  # métricas
├── test_backtester.py               # Backtester
└── test_web.py                      # 24 testes (FastAPI web)
Fases concluídas
F0 ✔ — Esqueleto
CLI (engine status | check-config | version)

EngineSettings (pydantic-settings)

BrokerGateway (Protocol) + RealMT5Gateway + FakeGateway

Logging estruturado (structlog)

F1 ✔ — Paridade do detector com EA v4.60
Paridade bit-a-bit confirmada (500 candles WIN$N M1)

Fixture golden (v510_expected.csv)

Semântica travada: janela inclusiva, desvio amostral, fonte TICK

F2a ✔ — Preset completo
7 seções: detector, session, entry, stop, take_profit, risk, regions

Validadores cruzados replicam o OnInit() do EA

F2b ✔ — RegionManager + pricing
TradeLocation, RegionState, RegionPhase

5 modos de entrada, 3 modos de SL, TP, regra de candle grande

F2c ✔ — TradingSession
Orquestrador de decisão (sem ordens, sem MT5)

Filtros de sessão, mute_open_min, TTL, cooldown, daily limit

F2d ✔ — Simulador
EventFeed, SimulatedExecutor, run_simulation

SL ganha empate no mesmo tick

F3a ✔ — RealExecutor + BrokerGateway expandido
place_order, cancel_order, modify_position, close_position

RealExecutor calcula volume e retorna ExecutionResult

F3b ✔ — TradeEventPoller
Lê history_deals, classifica em 5 tipos

TradingSession.on_trade_event reage

F3c ✔ — Persistência SQLite
StateStore (Protocol), InMemoryStateStore, SqliteStateStore

F3d ✔ — engine run
Loop real + demo + dry-run + fast + max-ticks

F4 ✔ — Modo sombra
ShadowReport, Divergence, ShadowComparer

Relatório JSON em reports/shadow_*.json

F5a ✔ — Parciais
PartialSpec, make_partial_specs

place_partial_orders, breakeven após Tier 1

F5b ✔ — By-risk sizing
SizingMode.BY_RISK (fixed_money / percent_balance)

F5c ✔ — Reforço
ReentryIntent, place_reentry_order, place_reentry_exits

F5d ✔ — Calendário B3
B3Calendar (feriados 2026-2027)

TradingWindow.session_shift

F5e ✔ — Slippage/spread + is_stop
SimulatedExecutor(slippage_points, spread_points)

OrderRequest.is_stop: bool

F5f ✔ — Multi-estratégia
StrategyConfig, StrategyRegistry

engine run --strategies=A,B

F6 ✔ — Backtester próprio
load_bars_csv, metrics.py, Backtester.run()

F7a ✔ — Frontend setup + status
FastAPI + HTMX + Pico + Jinja2

F7b-1 ✔ — Tabela trades no SQLite
TradeRecord, save_trade, list_trades, list_equity

F7b-2 ✔ — Dashboard completo
GET /api/trades, GET /api/equity, uPlot

F7c ✔ — Config
GET/POST /api/preset, formulário com 7+ blocos

F7d ✔ — Backtest
GET/POST /api/backtest, upload CSV

F7e ✔ — Shadow (read-only)
GET/POST /api/shadow, ShadowComparer read-only

F7f ✔ — SSE
GET /stream, StreamingResponse, hx-ext="sse"

F7g ✔ — Testes de cobertura web
24 testes em test_web.py

F8 ✔ — Parciais/reforço no simulador
SimulatedExecutor agora simula parciais e reforço

F9 ✔ — Modo Armadilha (Trap)
trigger_mode: trap, inverte a direção do rompimento

trap_arm_points, trap_style, trap_sl_points

F10 ✔ — Gráfico de Candles
Lightweight Charts + volume + timeframes (1M, 5M, 15M, 30M, 4H, D, M)

Ferramenta de medição (Shift + arrastar)

F11 ✔ — Multi-símbolo
--symbols=WIN$N,WDO$N no engine run

TradingSession recebe symbol no __init__

F12 ✔ — Observabilidade (Prometheus)
Endpoint GET /metrics (formato text/plain)

Contadores de trades abertos/fechados, PnL, taxa de acerto

F13 ✔ — Operação Demo (Validação em conta real)
Trava Anti-Spam: _make_intent verifica _current_entry_region e retorna None se já houver um trade em andamento (impede ordens duplicadas).

Warm-up Histórico: _warmup_historico no cli.py puxa 2500 candles (~2 dias) e salva os trigger_candle no banco.

Candle Gatilho (Roxo): Rota /api/history_markers e dashboard.html pintam setas roxas acima dos candles gatilho.

Dashboard em Tempo Real: stream.py envia JSON com dados da conta, detector, status e candles. dashboard.html usa JavaScript para atualizar os números e o gráfico via candleSeries.update().

Correção de Expiração: gateway.py usa ORDER_TIME_DAY em vez de GTC (Clear não aceita GTC para WINZ26).

Correção do Loop: process_strategy_tick só chama _save_trigger_candle quando o candle é novo, evitando duplicação.

Decisões de arquitetura (registradas)
Tema	Decisão
Config	Pydantic 2 + pydantic-settings (.env)
Backtest	.mq5 (Strategy Tester) ou engine backtest (F6)
Estado	SQLite (regiões + session_state + trades), schema auto-criado
Semântica detector	Idêntica ao EA (janela inclusiva, desvio amostral)
Sizing	Fixo (total_contracts * lot_per_contract) ou by-risk
Modelo de execução	SL ganha empate no simulador (conservador, MT5-style)
RegionManager	dict mutável + enum de fase; MAX_LOC=12
Datas	Sempre aware UTC nos métodos públicos
Modo sombra	Magic do EA por parâmetro; comparação por bar_time
Parciais (F5a)	comment=engine_partial_N
Reforço (F5c)	comment=engine_reentry (entrada) e _tp/_sl (saídas)
Calendário B3 (F5d)	Feriados 2026-2027 hardcoded
Slippage (F5e)	SimulatedExecutor(slippage_points, spread_points)
is_stop (F5e)	Campo explícito no OrderRequest
Multi-estratégia (F5f)	StrategyRegistry + --strategies=A,B
Backtester (F6)	Backtester reusa SimulatedExecutor + EventFeed
Frontend (F7a)	FastAPI + HTMX + Pico + Jinja2
Gráficos (F7b-2/F10)	uPlot (equity) + Lightweight Charts (candles)
SSE (F7f)	StreamingResponse + hx-ext="sse"
Modo Trap (F9)	trigger_mode: trap, inverte direção, SL/TP recalculados
Multi-símbolo (F11)	--symbols=WIN$N,WDO$N; uma sessão por símbolo
Observabilidade (F12)	Endpoint /metrics (Prometheus)
Operação Demo (F13)	Trava Anti-Spam + Warm-up + Gatilhos Roxos + Dashboard ao vivo
Expiração (F13)	mt5.ORDER_TIME_DAY (GTC rejeitado pela Clear)
Fuso Horário (F13)	⚠️ Pendente de correção (ver seção de Bugs)
Roadmap
Fase	Descrição	Status
F0	Esqueleto (CLI, config, ACL, fake)	✔
F1	Paridade do detector com EA v4.60	✔
F2a	Preset completo (7 seções) + validadores	✔
F2b	RegionManager + TradeLocation + pricing	✔
F2c	TradingSession (filtros de sessão + TradeIntent)	✔
F2d	Simulador (EventFeed + SimulatedExecutor)	✔
F3a	RealExecutor + BrokerGateway expandido	✔
F3b	TradeEventPoller + notificações	✔
F3c	Persistência SQLite	✔
F3d	engine run (loop real + demo)	✔
F4	Modo sombra (compara decisões com EA)	✔
F5a	Parciais (tiers 1/2/3) + breakeven	✔
F5b	By-risk sizing	✔
F5c	Reforço no retorno à entrada	✔
F5d	Validade por pregões reais (calendário B3)	✔
F5e	Slippage/spread + is_stop	✔
F5f	Multi-estratégia	✔
F6	Backtester próprio	✔
F7a	Frontend setup + status	✔
F7b-1	Tabela trades no SQLite	✔
F7b-2	Dashboard completo (equity + trades)	✔
F7c	Config (edição de preset)	✔
F7d	Backtest (upload CSV + resultado)	✔
F7e	Shadow (read-only)	✔
F7f	SSE (status em tempo real)	✔
F7g	Testes de cobertura web (24 testes)	✔
F8	Parciais/reforço no simulador	✔
F9	Modo Armadilha (Trap)	✔
F10	Gráfico de Candles (volume, timeframes, medição)	✔
F11	Multi-símbolo (--symbols)	✔
F12	Observabilidade (Prometheus /metrics)	✔
F13	Operação Demo (Trava Anti-Spam, Warm-up, Gatilhos Roxos)	✔
F14	Correção de Fuso Horário (Dashboard vs MT5)	⏳ próximo
F15	Log Detalhado de Trades (frontend com PnL)	⏳ futuro
Suíte de testes
powershell
uv run pytest -q                              # ~241 testes
uv run pytest -v                              # verbose
uv run pytest tests/test_golden_v510.py -v    # paridade do detector
uv run pytest tests/test_calendar.py -v       # calendário B3
uv run pytest tests/test_state.py -v          # persistência
uv run pytest tests/test_run.py -v            # engine run
uv run pytest tests/test_shadow.py -v         # modo sombra
uv run pytest tests/test_partials.py -v       # parciais
uv run pytest tests/test_reentry.py -v        # reforço
uv run pytest tests/test_registry.py -v       # multi-estratégia
uv run pytest tests/test_csv_loader.py -v     # CSV loader
uv run pytest tests/test_metrics.py -v        # métricas
uv run pytest tests/test_backtester.py -v     # Backtester
uv run pytest tests/test_web.py -v            # frontend (F7a-F13)
Comandos úteis (CLI + Frontend)
powershell
# Backend (CLI)
uv run engine version
uv run engine check-config                         # audita preset (7 seções)
uv run engine status --fake                        # detector + gateway sintético
uv run engine status                               # detector + gateway real
uv run engine run --dry-run --fast --max-ticks 10  # loop de teste
uv run engine run --dry-run --fast --max-ticks 3 --strategies=stddev_v510
uv run engine run --demo --symbols=WINZ26 > logs_demo.txt 2>&1 # operação demo
uv run engine run --demo --symbols=WIN$N,WDO$N     # multi-símbolo
uv run engine shadow --ea-magic 20260718 --duration 60
uv run engine backtest --csv PATH

# Frontend
uv run uvicorn engine.web.app:app --reload --port 8000
# Abrir: http://localhost:8000          (dashboard, com SSE)
#        http://localhost:8000/config   (config)
#        http://localhost:8000/backtest (backtest + gráfico)
#        http://localhost:8000/shadow   (shadow - read only)
#        http://localhost:8000/metrics  (Prometheus - F12)
Bugs conhecidos / pontos de atenção
Fuso Horário (F13): O Dashboard exibe horários errados nos trigger_candles (ex: 03:03 em vez de 09:03). O servidor da Clear envia o horário em UTC, e as camadas de conversão (gateway.py + trades.py) estão subtraindo horas em dobro. Solução sugerida: Reverter o gateway.py para salvar em UTC puro; no trades.py, usar o horário bruto do banco (sem conversão); descobrir o offset exato do servidor da Clear.

tzdata no Windows: O pacote tzdata precisa estar instalado para ZoneInfo funcionar no Windows.

Código morto: O arquivo routes/backtest.py tem um segundo return JSONResponse inalcançável (limpar na próxima sessão).

TemplateNotFound: partials começam com _, páginas não.

HTMX upload: hx-encoding="multipart/form-data".

SSE: StreamingResponse(media_type="text/event-stream").

Modo Trap: trigger_mode é string ("trap" ou "normal").

/metrics vazio: Comportamento esperado (processo web separado do CLI).

Referências
EA de referência: StdDevVolumeBreakout.mq5 v4.60 (Renan)

Indicador companheiro: VolumeStdBarPainter.mq5 v3.00 e v1.00

Script golden: z_dump.mq5 (exporta candles + z-score para CSV)

Fixture real: tests/fixtures/v510_expected.csv (679 candles)

Plano completo: Plano_Motor_Trading_Python.md

Guia único de retomada: AI.md (backend + frontend)

Manual de uso: MANUAL.md (passo a passo de operação)