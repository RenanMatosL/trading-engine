# Trading Engine — Motor Multi-Estratégia

Porte da estratégia **StdDevVolumeBreakout v4.60** para Python (API oficial
MetaTrader5), arquitetado em DDD/bounded contexts para múltiplas estratégias
plugáveis. Plano completo: `Plano_Motor_Trading_Python.md`.

**Estado atual:** F0 → F5a concluídos. O motor **detecta** sinais (paridade
bit-a-bit com o EA), **gerencia** regiões, **orquestra** sessão, **simula**
trades, **executa** ordens (real + fake), **reage** a fills/SL/TP,
**persiste** estado em SQLite, **roda em loop** real, **compara** decisões
com o EA em tempo real (modo sombra) e **opera com parciais** (tiers 1/2/3)
com breakeven após Tier 1. F5b (by-risk sizing) é o próximo passo.

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
uv run engine run --demo --db engine_demo.db        # loop real em demo
uv run engine shadow --ea-magic 20260718 --duration 60   # modo sombra
uv run pytest -q                  # suíte completa (~148 testes)
```

Linux/macOS (desenvolvimento sem MT5): `uv pip install -e ".[dev]"` e usar `--fake`.

---

## Estrutura atual

```
src/engine/
├── domain/                          # PURO: zero imports externos
│   ├── shared/types.py              # Bar, Side, VolumeSource, MarketSnapshot
│   ├── risk/calendar.py             # TradingWindow
│   ├── state/store.py               # StateStore (Protocol) + SessionSnapshot (F3c)
│   └── strategy/
│       ├── detector.py              # VolumeStdDetector (paridade bit-a-bit EA)
│       ├── location.py              # TradeLocation, RegionState, RegionPhase, RegisterResult
│       ├── regions.py               # RegionManager (governança, TTL, validade, rearme)
│       └── pricing.py               # entry_level / stop_level / take_profit_level
│                                    #   + PricingConfig + Enums de modo
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
│   ├── executor.py                  # RealExecutor (+ close_all_at_end_of_day)
│   ├── shadow_report.py             # ShadowReport + Divergence (F4)
│   ├── shadow.py                    # ShadowComparer (F4)
│   └── partial_spec.py              # PartialSpec + make_partial_specs (F5a)
│
├── infrastructure/                  # ACL MetaTrader5 + persistência
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
presets/
└── stddev_v510_default.yaml         # todos os inputs do EA v4.60 comentados
tests/
├── fixtures/v510_expected.csv       # 679 candles WIN$N M1 + z-score do MT5
├── test_calendar.py
├── test_detector.py
├── test_presets.py
├── test_golden_v510.py              # paridade bit-a-bit vs EA v4.60
├── test_regions.py
├── test_pricing.py
├── test_trading_session.py
├── test_simulation.py
├── test_executor.py
├── test_poller.py
├── test_state.py
├── test_run.py
├── test_shadow.py                   # modo sombra
└── test_partials.py                 # parciais + integração (F5a)
```

---

## Fases concluídas

### F0 ✔ — Esqueleto
- CLI (`engine status | check-config | version`)
- `EngineSettings` (pydantic-settings, prefixo `ENGINE_`, nested `__`)
- `BrokerGateway` (Protocol) + `RealMT5Gateway` (import tardio) + `FakeGateway`
- Logging estruturado (structlog: console legível ou JSON)
- Empacotamento `src/` layout, entry point `engine = engine.cli:main`

### F1 ✔ — Paridade do detector com EA v4.60
- **Paridade bit-a-bit confirmada** em 500 candles reais do `WIN$N M1`
- Fixture golden gerado pelo script `z_dump.mq5` rodado no MT5 (679 candles)
- Semântica travada: janela **inclui** o candle avaliado, desvio **amostral (n−1)**,
  fonte TICK, candle em formação excluído
- Teste `test_golden_v510.py` falha se alguém quebrar a fórmula

### F2a ✔ — Preset completo
- 7 seções em `StdDevV510Preset`: `detector`, `session`, `entry`, `stop`,
  `take_profit`, `risk`, `regions`
- **Validadores cruzados** replicam o `OnInit()` do EA (combinações inválidas
  de entry/SL, soma de parciais, pontos crescentes, offsets de candle grande)
- `presets/stddev_v510_default.yaml` mapeia cada valor ao input MQL5
- `engine check-config` audita todas as 7 seções

### F2b ✔ — RegionManager + pricing
- `TradeLocation` (fato imutável) + `RegionState` (estado mutável) + `RegionPhase` (enum)
- `RegionManager`: registro, rompimento, governança, TTL, validade, rearme
- `pricing.py`: 5 modos de entrada, 3 modos de SL, TP, regra de candle grande
- `CandidateMode`: `HIGHEST_VOLUME` (default) e `FIRST_READY`
- 16 testes de regiões + 17 de pricing

### F2c ✔ — TradingSession
- Orquestrador de decisão (sem ordens, sem MT5)
- `on_bar_closed(bar, zscore, now)` — filtro `mute_open_min` + registro de região
- `on_tick(snapshot)` — rompimento, TTL, filtros de sessão, `TradeIntent`
- Filtros: horário operacional, entry block, cooldown pós-SL, limite diário,
  carry delay, `mute_open_min`
- `TradeIntent` (frozen): região + nível de entrada + SL + TP + volume + as_pending

### F2d ✔ — Simulador (F6-lite)
- `EventFeed` (`BarEvent | TickEvent`) em ordem cronológica
- `SimulatedExecutor`: fill de limite quando `bid <= entry` (compra) /
  `ask >= entry` (venda); SL **ganha empate** dentro do mesmo tick
- `run_simulation(feed, preset)` → `SimulationResult` (trades + equity + stats)
- 7 testes do simulador (SL, TP, empate, end-to-end)

### F3a ✔ — RealExecutor + BrokerGateway expandido
- `BrokerGateway` expandido: `place_order`, `cancel_order`, `modify_position`,
  `close_position`, `positions`, `orders`, `history_deals`
- `RealExecutor`: calcula volume (fixed_contracts), chama `place_order`, retorna `ExecutionResult`
- `ExecutionResult` com `.is_ok` + `.ok` (alias)
- 7 testes de executor (market, limit, cancel, close, modify)

### F3b ✔ — TradeEventPoller + notificações
- `TradeEventPoller`: lê `history_deals`, classifica em 5 tipos (`EntryFilled`,
  `PartialFilled`, `StopLossHit`, `TakeProfitHit`, `PositionClosed`)
- Idempotência via `_last_deal_ticket`
- `TradingSession.on_trade_event`: reage (cooldown, rearme, consume)
- `RiskParams` ganhou `use_reverse` + `reuse_sl_signal`
- 10 testes de poller + 7 testes de `on_trade_event`

### F3c ✔ — Persistência SQLite
- `StateStore` (Protocol) + `SessionSnapshot` (dataclass frozen)
- `InMemoryStateStore` (testes) + `SqliteStateStore` (produção, com schema auto-criado)
- `TradingSession` ganhou `state_store` opcional + `save_state()` + `_load_state()`
- Todas as mutações chamam `save_state()` (no-op se `state_store is None`)
- 13 testes (11 de store + 2 de integração)

### F3d ✔ — `engine run` (loop real + demo)
- Subcomando `engine run` com `--dry-run`, `--demo`, `--db`, `--poll-interval`,
  `--max-ticks`, `--fast`
- `TickInfo` + `symbol_info_tick(symbol)` no `BrokerGateway`
- `RealExecutor.close_all_at_end_of_day` (fecha posições + cancela pendentes)
- Loop: tick → snapshot → on_tick → executor; poller; new bar → on_bar_closed;
  fim do dia → close_all_at_end_of_day; save_state
- 4 testes (`test_run.py`)

### F4 ✔ — Modo sombra
- `ShadowReport` + `Divergence` (dataclasses frozen, serializáveis)
- `ShadowComparer.compare`: match por `(bar_time, is_buy, entry_price ± tolerance)`
- `engine shadow`: subcomando com `--ea-magic`, `--py-magic`, `--duration`,
  `--tolerance-points`, `--report-dir`, `--db`
- Relatório JSON em `reports/shadow_YYYYMMDD_HHMMSS.json`
- 6 testes (`test_shadow.py`)

### F5a ✔ — Parciais (tiers 1/2/3)
- `PartialSpec` + `make_partial_specs`: tiers 1/2/3 com pontos/percent
- `TradeIntent.partials: tuple[PartialSpec, ...] | None`
- `RealExecutor.place_partial_orders(intent, symbol)`: arma N ordens limite
  (comment `engine_partial_N` para o Poller classificar)
- `TradingSession._infer_tier_from_comment` + `_partials_filled`
- `engine run`: chama `place_partial_orders` após `execute()` OK; breakeven
  após Tier 1 (se `breakeven_after_partial=True`)
- 18 testes (`test_partials.py`: 12 spec + 6 integração)

---

## Decisões de arquitetura (registradas)

| Tema | Decisão |
|---|---|
| Config | Pydantic 2 + pydantic-settings (.env); Pulumi adiado até deploy em nuvem |
| Backtest | `.mq5` (Strategy Tester) até F6; simulador Python em F2d valida lógica |
| Estado | SQLite em F3c (regiões + session_state), com schema auto-criado |
| Barramento | Interno síncrono; RabbitMQ só se distribuir (F5+) |
| Semântica detector | **Idêntica ao EA** (janela inclusiva, desvio amostral, fórmula de uma passada) |
| Sizing | Fixo (`total_contracts * lot_per_contract`); by-risk em F5b |
| Modelo de execução | SL ganha empate no simulador (conservador, MT5-style) |
| `RegionManager` | dict mutável + enum de fase (evita flags impossíveis); `MAX_LOC=12` |
| Filtro de abertura | `mute_open_min` no `TradingSession` (não no `RegionManager`) |
| Volume REAL | Fallback REAL→TICK no domínio (defensável; `WIN$N` tem real_volume > 0) |
| Datas | Sempre `aware UTC` nos métodos públicos; normalizar `since` naive |
| Modo sombra | Magic do EA por parâmetro (não hardcoded); comparação por `bar_time` |
| Parciais (F5a) | `comment=engine_partial_N` no `place_partial_orders`; `_infer_tier_from_comment` extrai o N |

---

## Roadmap

| Fase | Descrição | Status |
|---|---|---|
| **F0** | Esqueleto (CLI, config, ACL, fake) | ✔ |
| **F1** | Paridade do detector com EA v4.60 (500 candles, tol=1e-9) | ✔ |
| **F2a** | Preset completo (7 seções) + validadores cruzados + YAML | ✔ |
| **F2b** | RegionManager + TradeLocation + pricing (5 modos entry, 3 SL) | ✔ |
| **F2c** | TradingSession (filtros de sessão + TradeIntent) | ✔ |
| **F2d** | Simulador (EventFeed + SimulatedExecutor + run_simulation) | ✔ |
| **F3a** | RealExecutor + BrokerGateway expandido | ✔ |
| **F3b** | TradeEventPoller + notificações | ✔ |
| **F3c** | Persistência SQLite | ✔ |
| **F3d** | `engine run` (loop real + demo) | ✔ |
| **F4** | Modo sombra (compara decisões com EA em tempo real) | ✔ |
| **F5a** | Parciais (tiers 1/2/3) + breakeven após Tier 1 | ✔ |
| **F5b** | By-risk sizing | ⏳ **próximo** |
| **F5c** | Reforço no retorno à entrada (`use_reentry`) | ⏳ pendente |
| **F5d** | Validade por pregões reais (calendário B3) | ⏳ pendente |
| **F5e** | Slippage/spread no simulador | ⏳ pendente |
| **F5f** | Multi-estratégia (`Strategy` Protocol + `StrategyRegistry`) | ⏳ pendente |
| **F6** | Backtester próprio (sem MT5, com slippage realista) | ⏳ pendente |

---

## Suíte de testes

```powershell
uv run pytest -q                              # ~148 testes
uv run pytest -v                              # verbose
uv run pytest tests/test_golden_v510.py -v    # só paridade do detector
uv run pytest tests/test_state.py -v          # persistência
uv run pytest tests/test_run.py -v            # engine run
uv run pytest tests/test_shadow.py -v         # modo sombra
uv run pytest tests/test_partials.py -v       # parciais (F5a)
```

Cobertura por módulo:

- `test_calendar.py` — `TradingWindow.is_open` (incl. cruzamento meia-noite)
- `test_detector.py` — detector (média, desvio amostral, sinal)
- `test_presets.py` — bounds + validadores cruzados (combinações inválidas)
- `test_golden_v510.py` — paridade bit-a-bit com EA v4.60 (500 candles)
- `test_regions.py` — RegionManager (criação, rompimento, governança, TTL, rearme)
- `test_pricing.py` — entry (5 modos), SL (3 modos), TP, candle grande
- `test_trading_session.py` — filtros de sessão + TradeIntent + on_trade_event
- `test_simulation.py` — simulador (SL, TP, empate, end-to-end)
- `test_executor.py` — executor (place/cancel/modify/close)
- `test_poller.py` — TradeEventPoller (classificação de deals)
- `test_state.py` — StateStore + integração com TradingSession
- `test_run.py` — engine run (dry-run, new bar, intent→exec, reação a SL)
- `test_shadow.py` — ShadowComparer (match, ea_only, py_only, mismatch, tolerância)
- `test_partials.py` — PartialSpec + integração (TradeIntent, Executor, Poller, Session)

---

## Comandos úteis (CLI)

```powershell
uv run engine version                              # versão
uv run engine check-config                         # audita preset (7 seções)
uv run engine status --fake                        # detector + gateway sintético
uv run engine status                               # detector + gateway real (MT5)
uv run engine run --dry-run --fast --max-ticks 10  # loop de teste (sem MT5)
uv run engine run --demo --db engine_demo.db       # loop real em demo
uv run engine shadow --ea-magic 20260718 --duration 60   # modo sombra
```

---

## Referências

- **EA de referência:** `StdDevVolumeBreakout.mq5` v4.60 (Renan)
- **Indicador companheiro:** `VolumeStdBarPainter.mq5` v3.00 (multi-nível) e v1.00 (simples)
- **Script golden:** `z_dump.mq5` (exporta candles + z-score para CSV)
- **Fixture real:** `tests/fixtures/v510_expected.csv` (679 candles `WIN$N M1`, 29/10/2026)
- **Plano completo:** `Plano_Motor_Trading_Python.md`
- **Guia de retomada:** `AI.md`