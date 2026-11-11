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
3. Aguarda rompimento de um extremo → define direção.
4. Entrada no pullback (meio do candle ou nível configurável), SL, TP.
5. Gerencia regiões com validade (2 pregões), TTL pós-rompimento (60 min),
   cooldown pós-SL (10 min), limite diário (3), filtros de horário e de abertura.
6. **Parciais** (tiers 1/2/3) + breakeven após Tier 1.
7. **Reforço** no retorno à entrada (1x por trade, com TP/SL próprios).
8. **Sizing** fixo ou by-risk (fixed_money / % do balance).
9. **Validade por pregões reais** (calendário B3, feriados 2026-2027).
10. **Multi-estratégia** (N sessões por tick, cada uma com seu magic).
11. **Backtester próprio** (sem MT5, com slippage/spread e métricas).
12. **Interface Web (F7)** (FastAPI + HTMX + Pico CSS + uPlot).
13. **Modo Armadilha (F9)** (inverte a direção do rompimento).
14. **Gráfico de Candles (F10)** (visualização dos trades em candles).
15. **Multi-símbolo (F11)** (rodar em N símbolos via `--symbols`).
16. **Observabilidade (F12)** (métricas Prometheus no endpoint `/metrics`).
17. **Operação Demo (F13)** (execução real em conta demo com Dashboard em tempo real).

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
| **F13** | Operação Demo: Trava Anti-Spam, Warm-up Histórico, Gatilhos Roxos, Dashboard em Tempo Real | ✅ fechado (exceto bug de fuso horário) |

**Suíte de testes atual:** **241 passed** (`uv run pytest -q`).
**Projeto completo (F0→F6 + F7a→F7g + F8 + F9 + F10 + F11 + F12 + F13).**

---

## 3. Arquitetura (mapa de arquivos)

```text
src/engine/
├── domain/                          # PURO: zero imports externos
│   ├── shared/types.py              # Bar, Side, VolumeSource, MarketSnapshot
│   ├── risk/
│   │   ├── calendar.py              # TradingWindow (+ session_shift)
│   │   └── exchange_calendar.py     # B3Calendar (feriados 2026-2027) — F5d
│   ├── state/store.py               # StateStore (Protocol) + SessionSnapshot + TradeRecord
│   └── strategy/
│       ├── detector.py              # VolumeStdDetector (paridade EA, F1)
│       ├── location.py              # TradeLocation, RegionState, RegionPhase, RegisterResult
│       ├── regions.py               # RegionManager (governança, TTL, validade, rearme)
│       ├── pricing.py               # entry_level / stop_level / take_profit_level
│       │                            #   + PricingConfig + Enums de modo + TrapMode (F9)
│       └── strategy.py              # StrategyConfig (F5f)
│
├── config/
│   ├── settings.py                  # EngineSettings (pydantic-settings, .env)
│   └── presets.py                   # StdDevV510Preset (7 seções + validadores cruzados + F9)
│
├── application/                     # orquestração (sem MT5, sem ordens)
│   ├── status.py                    # get_status (F0/F1)
│   ├── intent.py                    # TradeIntent, ReentryIntent, TickDecision, BarResult
│   ├── trading_session.py           # TradingSession (+ state_store + on_trade_event +
│   │                                #   calendar + persistência + save_trade + F9 + F11 + F13)
│   ├── events.py                    # EventFeed, BarEvent, TickEvent (F2d)
│   ├── simulation.py                # run_simulation, SimulatedExecutor
│   │                                #   + slippage/spread (F5e)
│   │                                #   + parciais/reforço (F8)
│   │                                #   + trap (F9)
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
│   ├── metrics_exporter.py          # F12: contadores Prometheus
│   ├── metrics.py                   # Sharpe, drawdown, win rate, etc (F6)
│   └── backtester.py                # Backtester + BacktestResult (F6)
│
├── infrastructure/                  # ACL MetaTrader5 + persistência + CSV
│   ├── mt5/
│   │   ├── gateway.py               # BrokerGateway (Protocol) + RealMT5Gateway
│   │   │                            #   + AccountInfo, SymbolInfo, TickInfo,
│   │   │                            #     PositionInfo, OrderInfo, DealInfo,
│   │   │                            #     OrderRequest (is_stop em F5e), OrderResult
│   │   │                            #   + F13: ORDER_TIME_DAY (correção expiração)
│   │   └── fake.py                  # FakeGateway (book sintético + _force_fill_pending)
│   ├── logging/setup.py             # structlog
│   ├── state/
│   │   ├── memory_store.py          # InMemoryStateStore (F3c + F7b-1)
│   │   └── sqlite_store.py          # SqliteStateStore + schema (F3c + F5e + F7b-1)
│   └── data/
│       └── csv_loader.py            # load_bars_csv (F6)
│
├── web/                             # Frontend (FastAPI) — F7a+
│   ├── app.py                       # App + rotas HTML + API
│   ├── deps.py                      # gateway, settings
│   ├── schemas.py                   # Pydantic schemas
│   ├── routes/                      # Routers (trades, equity, preset, backtest, shadow, stream, metrics)
│   │   └── trades.py                # F13: /api/trades, /api/history_markers, /api/candles, /api/active_trade
│   ├── templates/                   # base.html, dashboard.html, partials _*.html
│   └── static/                      # htmx, pico, uplot, sse, lightweight-charts
│
└── cli.py                           # engine status | check-config | run | shadow |
                                     #   backtest | version
                                     # F13: _warmup_historico, _save_trigger_candle

presets/
└── stddev_v510_default.yaml         # todos os inputs do EA v4.60 comentados
tests/
├── fixtures/
│   ├── v510_expected.csv            # 679 candles WIN$N M1 + z-score do MT5
│   ├── sample_bars.csv              # 10 candles (F6)
│   └── WINZ26_M1_1_a_6_nov_26.csv   # 6 dias de nov (novo)
├── test_calendar.py                 # TradingWindow + B3Calendar + session_shift (F5d)
├── test_detector.py
├── test_presets.py
├── test_golden_v510.py              # paridade bit-a-bit vs EA v4.60
├── test_regions.py                  # RegionManager + validade por pregões reais
├── test_pricing.py
├── test_trading_session.py
├── test_simulation.py               # simulador + slippage/spread (F5e) + parciais/reforço (F8)
├── test_executor.py                 # executor + by-risk (F5b) + is_stop (F5e)
├── test_poller.py                   # TradeEventPoller (+ reentry em F5c)
├── test_state.py                    # StateStore + persistência (F5e + F7b-1)
├── test_run.py
├── test_shadow.py                   # modo sombra
├── test_partials.py                 # parciais + integração (F5a)
├── test_reentry.py                  # reforço (F5c)
├── test_registry.py                 # StrategyRegistry (F5f)
├── test_csv_loader.py               # load_bars_csv (F6)
├── test_metrics.py                  # métricas (F6)
├── test_backtester.py               # Backtester (F6)
└── test_web.py                      # TestClient FastAPI (F7a-F7g) — 24 testes
4. Decisões de arquitetura (NÃO MUDE SEM MOTIVO FORTE)
Domínio puro (Backend)
domain/ não importa MT5, pydantic, structlog, nem nada externo.

MarketSnapshot em domain/shared/types.py é a "foto do mercado" no tick.

Bar representa candle fechado (nunca em formação).

Semântica do detector = EA v4.60 EXATAMENTE
Janela inclui o candle avaliado ([i-L+1, i]).

Desvio amostral (n-1).

Fórmula de uma passada: var = (sumsq - sum*mean)/(n-1).

Se mexer nisso, test_golden_v510.py falha. É de propósito.

B3Calendar (F5d)
Lista hardcoded de feriados 2026-2027. Atualiza uma vez por ano.

is_trading_day(d) — segunda a sexta, exceto feriados.

trading_days_between(start, end) — conta pregões (negativo se start > end).

Não move feriados que caem em fim de semana.

TODO F13+: atualizar feriados 2028+.

TradingWindow.session_shift(bar_time, now, calendar)
Retorna calendar.trading_days_between(bar_time.date(), now.date()).

Se calendar is None, fallback para dias corridos.

Não usa start/end do TradingWindow (só bar_time e now).

RegionManager
Fila dict[bar_time, RegionState], limite max_loc=12 (paridade com EA).

Fila cheia substitui a de menor volume.

RegionPhase é enum explícito (WAITING_BREAKOUT / BROKEN / CONSUMED / REARMED).

NÃO aplica filtros de sessão (isso é TradingSession).

F5d: __init__ aceita calendar: B3Calendar | None = None.

TradingSession
Não executa ordens. Não consulta MT5.

Emite TradeIntent (frozen) — o Executor executa.

Filtros de sessão em on_tick: horário, entry_block, cooldown, daily_limit, carry_delay.

Filtro de abertura (mute_open_min) em on_bar_closed.

F11: __init__ aceita symbol e guarda em _symbol.

F12: chama record_trade_opened e record_trade_closed do metrics_exporter.

F13: TRAVA ANTI-SPAM em _make_intent: se _current_entry_region não for nulo, retorna None.

TradeIntent
volume = 0.0 até o Executor preencher.

as_pending=True → Executor usa BuyLimit/SellLimit.

as_pending=False → Executor usa Buy/Sell (a mercado).

F5a: partials: tuple[PartialSpec, ...] | None.

ReentryIntent (F5c)
Emitida pelo TradingSession._maybe_reentry no TickDecision.reentry_intent.

Contém: entry_price, is_buy, contracts, tp_points, sl_points, created_at.

1 reforço por trade (_reentry_done=True).

PartialSpec (F5a)
tier_index: 0, 1, 2.

contracts: quantos contratos sair neste tier.

points + percent: alvo em pontos ou % da entrada.

target_price(entry, is_buy, exit_type) → preço-alvo do tier.

StrategyConfig (F5f)
name: identificador único (ex: stddev_v510).

preset: StdDevV510Preset (validado pelo pydantic).

magic: magic number do MT5.

BrokerGateway (Protocol) + ACL
Domínio nunca importa MetaTrader5. Sempre conversa com o Protocol.

RealMT5Gateway: import tardio.

FakeGateway: book sintético para desenvolvimento/testes em qualquer SO.

IMPORTANTE: o OrderResult tem @property is_ok (não ok).

F5e: OrderRequest.is_stop: bool = False.

F13: place_order e close_position usam mt5.ORDER_TIME_DAY (GTC é rejeitado pela Clear).

StateStore (F3c + F5e + F7b-1)
StateStore é Protocol (domínio puro).

SessionSnapshot é frozen e serializável (10 campos).

F5e: persiste parciais/reforço entre reinícios.

F7b-1: SqliteStateStore tem tabela trades (TradeRecord).

save_trade(), list_trades(limit), list_equity(limit).

Datas sempre ISO 8601 UTC.

F13: _save_trigger_candle salva um TradeRecord com exit_reason="trigger_candle" (usado para pintar o gráfico).

Backtester (F6 + F8 + F10)
Consome list[Bar] (do csv_loader).

Constrói EventFeed:

BarEvent(bar, zscore) para cada candle.

2 TickEvent (open e close) para cada candle.

Roda run_simulation(feed, preset, ...) → SimulationResult.

F8: o SimulatedExecutor simula parciais e reforço.

F10: retorna JSON com candles, volumes, markers e summary.

Calcula métricas via metrics.py.

Interface Web (F7 + F10 + F13)
Stack: FastAPI + Jinja2 + HTMX + Pico CSS + uPlot + SSE + Lightweight Charts.

Sem build step. Sem Node.js. Bundle < 250 KB.

F13: O stream.py envia JSON (não HTML) para o Dashboard.

F13: O dashboard.html usa JavaScript para atualizar os números e o gráfico.

F13: /api/history_markers lê os trigger_candle do banco e envia setas roxas para o gráfico.

Operação Demo (F13) — O Que Foi Implementado
Trava Anti-Spam: Impede ordens duplicadas (bug crítico do loop).

Warm-up Histórico: Puxa 2500 candles (2 dias) e salva os gatilhos no banco.

Candle Gatilho (Roxo): Seta roxa (arrowDown) acima do candle no gráfico.

Dashboard em Tempo Real: SSE + JavaScript + Lightweight Charts.

🚨 O BUG DE FUSO HORÁRIO (Pendente de Correção)
O que acontece: O Dashboard exibe horários errados nos trigger_candles (ex: 03:03 em vez de 09:03).

Por que: O servidor da Clear envia o horário em UTC. O gateway.py subtraía 3h antes de salvar. O trades.py subtraía mais 3h para exibir. A conta fica errada em 6h.

O que foi tentado: astimezone(), ZoneInfo, timedelta. Nenhuma funcionou.

O que fazer na próxima sessão:

Reverter o gateway.py para salvar em UTC puro.
No trades.py, usar o horário bruto do banco (sem conversão).
Descobrir o offset exato do servidor da Clear (provavelmente GMT+0 ou GMT+2).
5. Próximos passos (F14+)
F14 — Correção de Fuso Horário (Urgente)
Corrigir a exibição de horários no Dashboard.

Alinhar o horário do MT5 (servidor da Clear) com o horário de Brasília.

F15 — Log Detalhado de Trades
Tabela de trades no frontend com data/hora exata de entrada/saída, SL/TP e PnL.

Rota /api/trades/log retorna trades reais (sem trigger_candle).

F16 — Observabilidade Real
Motor (CLI) e servidor (web) compartilharem métricas via SQLite.

6. Comandos úteis
powershell
# Testes
uv run pytest -q                              # 241 passed
uv run pytest tests/test_golden_v510.py -v    # paridade do detector
uv run pytest tests/test_web.py -v            # frontend

# CLI
uv run engine run --demo --symbols=WINZ26     # operação demo (motor)
uv run engine backtest --csv PATH             # backtest

# Frontend
uv run uvicorn engine.web.app:app --port 8000
# Abrir: http://localhost:8000          (dashboard)
#        http://localhost:8000/backtest (gráfico de candles)
#        http://localhost:8000/metrics  (Prometheus)

# Git
git add .
git commit -m "feat(F13): operacao demo, trava anti-spam e dashboard em tempo real"
git push origin main
7. Como o próximo agente deve começar
Passo 1 — Confirmar estado atual:

powershell
uv run pytest -q
Deve mostrar 241 passed. Se não, PARE e investigue o que quebrou.

Passo 2 — Ler este AI.md inteiro. Principalmente a seção 4 (decisões) e 5 (próximos passos F14+).

Passo 3 — Rodar uv run engine check-config para confirmar que o preset carrega.

Passo 4 — Subir o frontend:

powershell
uv run uvicorn engine.web.app:app --port 8000
Abra http://localhost:8000 → dashboard deve carregar.
Abra http://localhost:8000/backtest → gráfico deve renderizar.

Passo 5 — Se algo quebrar:

Rodar uv run pytest -q -x (para no primeiro erro).

Comparar com test_golden_v510.py se for detector, com test_regions.py se for região, com test_presets.py se for config, com test_web.py se for frontend.

NÃO consertar teste quebrando código de produção.

8. Bugs conhecidos / pontos de atenção
TemplateNotFound: partials começam com _, páginas não.

HTMX upload: hx-encoding="multipart/form-data".

SSE: StreamingResponse(media_type="text/event-stream").

Modo Trap: trigger_mode é string ("trap" ou "normal").

/metrics vazio: Comportamento esperado (processo web separado do CLI).

Fuso Horário: Pendente de correção (ver seção 4).

tzdata no Windows: O pacote tzdata precisa estar instalado para ZoneInfo funcionar.

Código morto: O arquivo routes/backtest.py tem um segundo return JSONResponse inalcançável (limpar na próxima sessão).

9. Referências externas
EA: StdDevVolumeBreakout.mq5 v4.60 (Renan).

Manual: MANUAL.md.

Frontend: README.md e AI.md (este arquivo).

10. Regras de ouro
Rode uv run pytest -q antes e depois de cada mudança.

Nunca cole código novo em cima do antigo sem remover.

Não mexa em domain/ sem rodar test_golden_v510.py e test_regions.py.

Sempre use OrderResult.is_ok (não .ok).

Sempre rode engine check-config depois de mexer no YAML.

engine shadow coloca ordens reais. Só use em demo.

Backtest com CSVs grandes via CLI (não web).

Datas sempre aware UTC (no banco), convertidas na exibição.

Gráfico F10: Shift + arrastar para medir pontos. Duplo clique limpa.

Multi-símbolo F11: --symbols=WIN$N,WDO$N.

Observabilidade F12: endpoint /metrics (Prometheus).

F13: A Trava Anti-Spam está no _make_intent. Não remova.