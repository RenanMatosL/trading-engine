markdown
# Trading Engine — Motor Multi-Estratégia

Porte da estratégia **StdDevVolumeBreakout v5.10** para Python (API oficial MetaTrader5),
arquitetado em DDD/bounded contexts para múltiplas estratégias plugáveis.
Plano completo: `Plano_Motor_Trading_Python.md`.

**Estado atual:** F0 → F4 concluídos. Detector com paridade bit-a-bit, preset
completo, gerenciador de regiões, orquestrador de sessão, simulador,
execução real (market + limit), persistência SQLite, loop `engine run`,
e modo sombra (comparação com EA em tempo real). **F5 (multi-estratégia +
parciais + reforço + by-risk + slippage) é o próximo passo.**

---

## Setup (Windows — máquina/VPS de produção)

```powershell
# 1. Instalar uv (uma vez):  https://docs.astral.sh/uv/
# 2. No diretório do projeto:
uv venv
uv pip install -e ".[mt5,dev]"
copy .env.example .env      # e preencha login/senha/servidor/símbolo

# 3. Rodar
uv run engine version
uv run engine check-config        # audita TODAS as 7 seções do preset
uv run engine status              # conecta no terminal MT5 aberto
uv run engine status --fake       # sem MT5 (gateway sintético p/ desenvolvimento)
uv run engine run --dry-run --fast --max-ticks 10   # loop de teste sem MT5
uv run pytest -q                  # suíte completa (~130 testes)
Linux/macOS (desenvolvimento sem MT5): uv pip install -e ".[dev]" e usar --fake.

Estrutura atual
text
src/engine/
├── domain/                          # PURO (zero deps externas)
│   ├── shared/types.py              # Bar, Side, VolumeSource, MarketSnapshot
│   ├── risk/calendar.py             # TradingWindow (janela de horário)
│   ├── state/store.py               # StateStore (Protocol) + SessionSnapshot
│   └── strategy/
│       ├── detector.py              # VolumeStdDetector (paridade bit-a-bit EA)
│       ├── location.py              # TradeLocation, RegionState, RegionPhase, RegisterResult
│       ├── regions.py               # RegionManager (governança, TTL, validade, rearme)
│       └── pricing.py               # entry_level / stop_level / take_profit_level
│
├── config/
│   ├── settings.py                  # pydantic-settings (.env) + MT5Settings
│   └── presets.py                   # StdDevV510Preset (7 seções + validadores cruzados)
│
├── application/                     # orquestração (sem MT5, sem ordens)
│   ├── status.py                    # get_status (F0/F1)
│   ├── intent.py                    # TradeIntent, TickDecision, BarResult
│   ├── trading_session.py           # TradingSession (+ state_store + on_trade_event)
│   ├── events.py                    # EventFeed, BarEvent, TickEvent (F2d)
│   ├── simulation.py                # run_simulation, SimulatedExecutor (F2d)
│   ├── trade_events.py              # EntryFilled, PartialFilled, StopLossHit,
│   │                                #   TakeProfitHit, PositionClosed (F3b)
│   ├── poller.py                    # TradeEventPoller (F3b)
│   ├── executor.py                  # RealExecutor (F3a + close_all_at_end_of_day)
│   ├── shadow_report.py             # ShadowReport + Divergence (F4)
│   └── shadow.py                    # ShadowComparer (F4)
│
├── infrastructure/                  # ACL MetaTrader5
│   ├── mt5/
│   │   ├── gateway.py               # BrokerGateway (Protocol) + RealMT5Gateway
│   │   │                            #   + AccountInfo, SymbolInfo, TickInfo,
│   │   │                            #     PositionInfo, OrderInfo, DealInfo,
│   │   │                            #     OrderRequest, OrderResult
│   │   └── fake.py                  # FakeGateway (determinístico, qualquer SO)
│   ├── logging/setup.py             # structlog (console / JSON)
│   └── state/
│       ├── memory_store.py          # InMemoryStateStore
│       └── sqlite_store.py          # SqliteStateStore + schema
│
└── cli.py                           # engine status | check-config | run | shadow | version
presets/                              # v510_default (todos os inputs do EA v4.60)
tests/
├── fixtures/
│   └── v510_expected.csv            # 679 candles WIN$N M1 + z-score do MT5
├── test_calendar.py
├── test_detector.py
├── test_presets.py                  # bounds + validadores cruzados
├── test_golden_v510.py              # paridade bit-a-bit vs EA v4.60
├── test_regions.py                  # RegionManager
├── test_pricing.py                  # entry/SL/TP + candle grande
├── test_trading_session.py          # filtros + TradeIntent + on_trade_event
├── test_simulation.py               # simulador
├── test_executor.py                 # executor (place/cancel/modify/close)
├── test_poller.py                   # TradeEventPoller
├── test_state.py                    # StateStore + persistência
├── test_run.py                      # engine run
└── test_shadow.py                   # ShadowComparer (F4)
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

Teste test_golden_v510.py falha se alguém quebrar a fórmula

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

TradeIntent (frozen): região + nível de entrada + SL + TP + volume + as_pending

F2d ✔ — Simulador (F6-lite)
EventFeed (BarEvent | TickEvent) em ordem cronológica

SimulatedExecutor: fill de limite quando bid <= entry (compra) /
ask >= entry (venda); SL ganha empate dentro do mesmo tick

run_simulation(feed, preset) → SimulationResult (trades + equity + stats)

7 testes do simulador (SL, TP, empate, end-to-end)

F3a ✔ — RealExecutor + BrokerGateway expandido
RealExecutor.execute(intent, symbol) → ExecutionResult

BrokerGateway expandido: place_order, cancel_order, modify_position,
close_position, positions, orders, history_deals

FakeGateway com book sintético (_force_fill_pending para testes)

7 testes do executor

F3b ✔ — TradeEventPoller + notificações
TradeEventPoller.poll(gateway, since, symbol, magic) → list[TradeEvent]

5 tipos: EntryFilled, PartialFilled, StopLossHit, TakeProfitHit, PositionClosed

TradingSession.on_trade_event(event, now) reage:

StopLossHit → cooldown + rearme/consume (via use_reverse/reuse_sl_signal)

TakeProfitHit / PositionClosed → consome região

10 testes do poller + 7 testes do on_trade_event

F3c ✔ — Persistência SQLite
StateStore (Protocol) + SessionSnapshot (frozen)

InMemoryStateStore (testes) + SqliteStateStore (produção)

Schema: session_state (key/value JSON) + regions

TradingSession.save_state() / _load_state() / _snapshot() — chamados em todas as mutações

Estado sobrevive a reinícios (regiões, cooldown, contador diário, região do trade atual)

13 testes do state store (5 memory + 6 sqlite + 2 integração)

F3d ✔ — engine run (loop real)
Subcomando run no CLI

Flags: --dry-run (FakeGateway), --demo (RealMT5Gateway), --preset, --db,
--poll-interval, --max-ticks, --fast

TickInfo + symbol_info_tick(symbol) no gateway (Real + Fake)

RealExecutor.close_all_at_end_of_day(symbol, now) — fecha posições no fim do dia

Loop: tick → snapshot → on_tick → executor; poller; new bar → on_bar_closed;
fim do dia → close_all; save_state

4 testes do engine run

F4 ✔ — Modo sombra
ShadowReport + Divergence — relatório de comparação EA ↔ Python

ShadowComparer.compare(ea_deals, py_trades, start, end, tolerance_points)
→ ShadowReport

Match por (bar_time, is_buy, entry_price ± tolerance_points) (default: 2 pontos)

Comando engine shadow --ea-magic 20260718 --py-magic 0 --duration 60

Gera JSON em reports/shadow_YYYYMMDD_HHMMSS.json com matched, ea_only,
py_only, mismatches, match_rate

6 testes do ShadowComparer

F5 ⏳ — Próximo passo
Sub-fases planejadas:

F5a — Parciais (tiers 1/2/3 do RiskParams)

F5b — By-risk sizing (_compute_volume com tick_value/tick_size)

F5c — Reforço (use_reentry no TradingSession + Executor)

F5d — Validade por pregões reais (calendário B3, não mais dias corridos)

F5e — Slippage/spread no simulador

F5f — Multi-estratégia (Strategy Protocol + StrategyRegistry)

F6 ⏳ — Backtester próprio
Consome CSV/Parquet de candles + ticks

Slippage realista, suporta parciais/reforço/by-risk/multi-estratégia

Exporta equity curve + trades + métricas (Sharpe, drawdown, win rate)

Compara com Strategy Tester do MT5

Decisões de arquitetura (registradas)
Tema	Decisão
Config	Pydantic 2 + pydantic-settings (.env); Pulumi adiado até deploy em nuvem
Backtest	.mq5 (Strategy Tester) até F6; simulador Python em F2d valida lógica
Estado	SQLite em F3c (regiões + sessão); sem migração de schema (F5)
Barramento	Interno síncrono; RabbitMQ só se distribuir (F5+)
Semântica detector	Idêntica ao EA (janela inclusiva, desvio amostral, fórmula de uma passada)
Sizing	Fixo (total_contracts * lot_per_contract); by-risk em F5
Modelo de execução	SL ganha empate no simulador (conservador, MT5-style)
RegionManager	dict mutável + enum de fase (evita flags impossíveis); MAX_LOC=12 no preset (paridade)
Filtro de abertura	mute_open_min no TradingSession (não no RegionManager)
Volume REAL	Fallback REAL→TICK no domínio (defensável; WIN$N tem real_volume > 0)
Execução	RealExecutor síncrono; OrderResult.is_ok (não .ok); ExecutionResult tem ambos (alias)
Persistência	save_state() em todas as mutações; InMemoryStateStore para testes, SqliteStateStore para produção
Modo sombra	Roda em paralelo ao EA (não interfere); relatório em JSON
Comandos úteis
powershell
# Testes (suíte completa: ~130 passed)
uv run pytest -q
uv run pytest tests/test_golden_v510.py -v    # paridade do detector
uv run pytest tests/test_shadow.py -v         # F4

# CLI
uv run engine version
uv run engine check-config                    # audita o preset (7 seções)
uv run engine status --fake                   # detector + gateway sintético
uv run engine status                          # detector + gateway real (MT5 aberto)
uv run engine run --dry-run --fast --max-ticks 10   # loop de teste sem MT5
uv run engine run --demo --db engine.db       # loop real em demo (MT5 aberto)
uv run engine shadow --ea-magic 20260718 --duration 60   # F4 (MT5 aberto)
Suíte de testes
powershell
uv run pytest -q           # ~130 testes
uv run pytest -v           # verbose
Cobertura por módulo:

test_calendar.py — TradingWindow.is_open (incl. cruzamento meia-noite)

test_detector.py — detector (média, desvio amostral, sinal)

test_presets.py — bounds + validadores cruzados

test_golden_v510.py — paridade bit-a-bit com EA v4.60 (500 candles)

test_regions.py — RegionManager (criação, rompimento, governança, TTL, rearme)

test_pricing.py — entry (5 modos), SL (3 modos), TP, candle grande

test_trading_session.py — filtros de sessão + TradeIntent + on_trade_event

test_simulation.py — simulador (SL, TP, empate, end-to-end)

test_executor.py — place/cancel/modify/close no FakeGateway

test_poller.py — classificação de deals (EntryFilled, SL, TP, partial, close)

test_state.py — StateStore (memory + sqlite + integração com sessão)

test_run.py — engine run (dry-run, detecção de candle, intent→execução, reação a SL)

test_shadow.py — ShadowComparer (perfeito, ea_only, py_only, mismatch, tolerância)

Referências
EA de referência: StdDevVolumeBreakout.mq5 v4.60 (Renan)

Indicador companheiro: VolumeStdBarPainter.mq5 v3.00 (multi-nível) e v1.00 (simples)

Script golden: z_dump.mq5 (exporta candles + z-score para CSV)

Fixture real: tests/fixtures/v510_expected.csv (679 candles WIN$N M1, 29/10/2026)

Plano completo: Plano_Motor_Trading_Python.md

Guia de retomada: AI.md

text

---

## ▶️ Passo a passo para aplicar

### Passo 1 — Salvar o `README.md`

```cmd
copy README.md README.md.bak
Depois abra o README.md no VSCode/PyCharm e substitua o conteúdo inteiro pelo bloco acima.

Passo 2 — Verificar que ficou correto
cmd
findstr /C:"F4 ✔" README.md
findstr /C:"~130 testes" README.md
findstr /C:"test_shadow.py" README.md
Esperado: 3 linhas (uma por findstr).

Passo 3 — Rodar a suíte para confirmar
cmd
uv run pytest -q
Esperado: 130 passed.

Passo 4 — Commit
cmd
git add README.md
git commit -m "docs: README atualizado F0→F4 (130 testes, modo sombra incluído)"