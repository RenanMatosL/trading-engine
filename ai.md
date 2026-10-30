AI.md — completo e atualizado (F0→F4 fechados, F5 próximo)
Substitua o conteúdo inteiro do AI.md por este:

markdown
# AI.md — Guia de Retomada do Projeto Trading Engine

> **Propósito deste arquivo:** permitir que uma IA (ou o autor) retome o projeto
> em outro chat/sessão **sem contexto anterior**, saiba **exatamente** onde
> paramos, o que falta, e o que **não pode ser quebrado**.
>
> **Leia este arquivo INTEIRO antes de escrever qualquer linha de código.**
> Ele evita retrabalho, decisões já tomadas e bugs conhecidos.

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
| **F5** | Multi-estratégia + parciais + reforço + by-risk + slippage | ⏳ **PRÓXIMO** |
| **F6** | Backtester próprio (sem MT5, com slippage realista) | ⏳ pendente |

**Suíte de testes atual:** **~130 passed** (`uv run pytest -q`).

---

## 3. Arquitetura (mapa de arquivos)

```
src/engine/
├── domain/                          # PURO: zero imports externos
│   ├── shared/
│   │   └── types.py                 # Bar, Side, VolumeSource, MarketSnapshot
│   ├── risk/
│   │   └── calendar.py              # TradingWindow
│   ├── state/
│   │   └── store.py                 # StateStore (Protocol) + SessionSnapshot (F3c)
│   └── strategy/
│       ├── detector.py              # VolumeStdDetector (paridade EA, F1)
│       ├── location.py              # TradeLocation, RegionState, RegionPhase,
│       │                            #   RegisterResult
│       ├── regions.py               # RegionManager (governança, TTL, validade, rearme)
│       └── pricing.py               # entry_level / stop_level / take_profit_level
│                                    #   + PricingConfig + Enums de modo
│
├── config/
│   ├── settings.py                  # EngineSettings (pydantic-settings, .env)
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
│   └── shadow.py                    # ShadowComparer (F4)
│
├── infrastructure/
│   ├── mt5/
│   │   ├── gateway.py               # BrokerGateway (Protocol) + RealMT5Gateway
│   │   │                            #   + AccountInfo, SymbolInfo, TickInfo,
│   │   │                            #     PositionInfo, OrderInfo, DealInfo,
│   │   │                            #     OrderRequest, OrderResult
│   │   └── fake.py                  # FakeGateway (book sintético + _force_fill_pending)
│   ├── logging/setup.py             # structlog
│   └── state/
│       ├── memory_store.py          # InMemoryStateStore (F3c)
│       └── sqlite_store.py          # SqliteStateStore + schema (F3c)
│
└── cli.py                           # engine status | check-config | run | shadow | version
presets/
└── stddev_v510_default.yaml         # todos os inputs do EA v4.60 comentados
tests/
├── fixtures/v510_expected.csv       # 679 candles WIN$N M1 + z-score do MT5
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
└── test_shadow.py                   # modo sombra (F4)
```

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

### `RegionManager`
- Fila `dict[bar_time, RegionState]`, limite `max_loc=12` (paridade com EA).
- Fila cheia substitui a de **menor volume** (governança por volume).
- `RegionPhase` é **enum explícito** (WAITING_BREAKOUT / BROKEN / CONSUMED / REARMED).
  **Não** use flags booleanas — gera estados impossíveis.
- **NÃO** aplica filtros de sessão (isso é `TradingSession`). Filtro de abertura
  (`mute_open_min`) também é responsabilidade do `TradingSession`, não do manager.
- Validade por pregões hoje usa dias corridos (aproximação). Refinar em F5
  com calendário de sessões (B3 tem feriados).

### `TradingSession`
- **Não** executa ordens. **Não** consulta MT5.
- Emite `TradeIntent` (frozen) — o `Executor` executa.
- Filtros de sessão em `on_tick`: horário, entry_block, cooldown, daily_limit, carry_delay.
- Filtro de abertura (`mute_open_min`) em `on_bar_closed`.
- Estado: `_last_sl_time`, `_trades_today`, `_current_day`, `_current_entry_region`, `_current_entry_position`.
- **F3b:** `on_trade_event(event, now)` consome `TradeEvent` do poller:
  - `EntryFilled` → rastreia `_current_entry_position`
  - `StopLossHit` → `notify_stop_loss` + rearme/consume da região (decidido por `use_reverse`/`reuse_sl_signal`)
  - `TakeProfitHit` / `PositionClosed` → consome a região
  - `PartialFilled` → no-op em F3b (F5 implementa)
- **F3c:** `state_store` opcional no `__init__`. `save_state()` serializa (snapshot + regiões), `_load_state()` desserializa. **Todas as mutações chamam `save_state()`** (no-op se `state_store is None`).

### `TradeIntent`
- `volume` = 0.0 até o `Executor` preencher (com `SymbolInfo`).
- `as_pending=True` → Executor usa BuyLimit/SellLimit.
- `as_pending=False` → Executor usa Buy/Sell (a mercado).

### `BrokerGateway` (Protocol) + ACL
- Domínio **nunca** importa `MetaTrader5`. Sempre conversa com o Protocol.
- `RealMT5Gateway`: import tardio (`import MetaTrader5 as mt5` dentro do método).
- `FakeGateway`: book sintético para desenvolvimento/testes em qualquer SO.
- **IMPORTANTE:** o `OrderResult` tem `@property is_ok` (não `ok`). O `ExecutionResult` do `executor.py` tem **as duas** (`.is_ok` + `.ok`, alias retrocompatível).
- **F3d:** `TickInfo` (dataclass) + `symbol_info_tick(symbol)` no Protocol e nas duas implementações.

### `StateStore` (F3c)
- `StateStore` é **Protocol** (domínio puro). Implementações em `infrastructure/state/`.
- `SessionSnapshot` é `frozen` e serializável (5 campos: `last_sl_time`, `trades_today`, `current_day`, `current_entry_region`, `current_entry_position`).
- Datas sempre ISO 8601 UTC.
- `SqliteStateStore` cria schema no `__init__` (`CREATE TABLE IF NOT EXISTS`).
- `save_regions` faz `DELETE + INSERT` (idempotente). Não há migração de schema (F5).

### `ShadowComparer` (F4)
- `ShadowReport` (frozen): `start`, `end`, `matched`, `ea_only`, `py_only`, `mismatches`, `divergences`.
- `Divergence` (frozen): `kind` (`ea_only` / `py_only` / `mismatch`), `bar_time`, `is_buy`, `ea_deal`, `py_price`, `detail`.
- Match por `(bar_time, is_buy, entry_price ± tolerance_points)`. Tolerância default 2.0.
- `match_rate = matched / max(total_ea, total_py)`. 1.0 = perfeito.
- Relatório JSON salvo em `reports/shadow_YYYYMMDD_HHMMSS.json`.
- **`ShadowComparer` não acessa MT5.** Roda com dados que o caller já coletou.
- **`engine shadow` acessa MT5** (precisa do `RealMT5Gateway`).

### Preset (`StdDevV510Preset`)
- 7 seções: `detector`, `session`, `entry`, `stop`, `take_profit`, `risk`, `regions`.
- Validadores cruzados replicam o `OnInit()` do EA:
  - `entry=opposite_extreme` + `stop=mid` → **inválido**
  - `entry=mid` + `stop=mid` + offsets=0 → **inválido**
  - Soma das parciais < `total_contracts`
  - Pontos das parciais estritamente crescentes
  - `big_candle_entry_offset < big_candle_min_range`
  - `use_partial_exit=True` exige ≥1 tier ativo
  - `exit_type=points` exige `partial_points > 0`; `exit_type=percent` exige `partial_percent > 0`
- O `YAML` **não** pode ter valores fora dos bounds (pydantic rejeita).

### `TradeEventPoller` (F3b)
- Estado: `_last_deal_ticket` (idempotência).
- A cada `poll()`: lê `history_deals(since, symbol, magic)`, filtra `ticket > _last_deal_ticket`, classifica via `_classify_deal`, atualiza `_last_deal_ticket`.
- Classificação:
  - `is_entry=True` → `EntryFilled`
  - `reason=4` (SL) → `StopLossHit`
  - `reason=5` (TP) → `TakeProfitHit`
  - `comment` contém `"partial"` → `PartialFilled`
  - resto → `PositionClosed`

### `engine run` (F3d)
- Subcomando `run` no `cli.py`.
- Flags: `--dry-run` (FakeGateway), `--demo` (RealMT5Gateway), `--preset`, `--db` (default `engine.db`), `--poll-interval` (default `1.0`), `--max-ticks` (0 = infinito), `--fast` (não dorme).
- Loop: tick → snapshot → on_tick → executor; poller; new bar → on_bar_closed; fim do dia (close_outside) → close_all_at_end_of_day; save_state.
- `KeyboardInterrupt` → save_state + shutdown.

### `engine shadow` (F4)
- Subcomando `shadow` no `cli.py`.
- Flags: `--ea-magic` (obrigatório), `--py-magic` (default 0), `--duration` (min, default 60), `--poll-interval` (default 2.0), `--tolerance-points` (default 2.0), `--report-dir` (default `reports/`), `--db` (default `engine_shadow.db`), `--preset`.
- Loop similar ao `engine run`, mas guarda `py_trades` (lista de `TradeIntent`) e, ao fim, lê `history_deals` do EA (magic dele) e chama `ShadowComparer.compare`.
- **Coloca ordens reais no MT5** (com o `py-magic`). Não é read-only — é um motor paralelo.
- **Requer MT5 aberto.** Não funciona com `--dry-run`.

### Sizing
- F3a usa **fixed_contracts** (`total_contracts * lot_per_contract`).
- `by_risk` fica para F5.

### Simulador (F2d)
- SL **ganha empate** dentro do mesmo tick (conservador, MT5-style).
- Parciais só ativam se `preset.risk.use_partial_exit=True` (híbrido, mas não implementado ainda).
- Volume = fixed_contracts (by-risk só em F5).

### Coisas que **NÃO podem ser quebradas**
1. `test_golden_v510.py` — paridade bit-a-bit com EA. **Sagrado.**
2. `test_regions.py` — semântica do `RegionManager`. **Sagrado.**
3. `test_presets.py` — validadores cruzados. **Sagrado.**
4. `test_pricing.py` — fórmulas de entry/SL/TP. **Sagrado.**
5. `test_simulation.py` — semântica de SL/TP no simulador. **Sagrado.**
6. `test_executor.py` — place/cancel/modify/close no gateway. **Sagrado.**
7. `test_poller.py` — classificação de deals. **Sagrado.**
8. `test_trading_session.py` — filtros + on_trade_event. **Sagrado.**
9. `test_state.py` — persistência. **Sagrado.**
10. `test_run.py` — engine run. **Sagrado.**
11. `test_shadow.py` — ShadowComparer. **Sagrado.**

Antes de qualquer mudança, **rode `uv run pytest -q`** e confirme que continua ~130 passed.

---

## 5. Próximo passo: F5 — Multi-estratégia + features completas

**Objetivo:** adicionar as features que faltam para paridade **total** com o EA v4.60, e preparar para múltiplas estratégias.

**O problema que F5 resolve:**
Hoje o motor é **fiel ao EA no básico** (detector, regiões, entrada, SL/TP, execução), mas **não implementa**:
- Parciais (tiers 1/2/3)
- Reforço no retorno à entrada
- By-risk sizing
- Slippage/spread no simulador
- Validade por pregões reais (B3)
- Multi-estratégia (paralelo)

**Arquitetura sugerida (em 6 sub-fases):**

### F5a — Parciais (~3 dias)
**O que implementa:** `InpUsePartialExit`, `InpExitType`, `InpPartialPoints`, `InpPartial2/3Points`, `InpPartialContracts`, `InpPartial2/3Contracts`, `InpPartialAsPending`, `InpBreakevenAfterPartial`.

**Arquivos a modificar:**
- `src/engine/application/executor.py` — adicionar `place_partial_orders(symbol, tiers, entry_price, is_buy)`
- `src/engine/application/trading_session.py` — `on_trade_event(PartialFilled)` consome tier e atualiza `_current_partials`
- `src/engine/application/poller.py` — distinguir `PartialFilled` de `PositionClosed` (já faz)
- `src/engine/application/intent.py` — `TradeIntent` ganha `partials: tuple[PartialSpec, ...] | None`
- `src/engine/application/simulation.py` — simulador simula parciais
- `tests/test_partials.py` — NOVO (~8 testes)

**Critérios de aceite:**
- `uv run pytest tests/test_partials.py -v` → 8 passed
- `uv run pytest -q` → ~138 passed
- Simulador com `use_partial_exit=True` gera trades com parciais

### F5b — By-risk sizing (~1 dia)
**O que implementa:** `InpSizingMode=SIZING_BY_RISK`, `InpRiskMode`, `InpRiskValue`.

**Arquivos a modificar:**
- `src/engine/application/executor.py` — `_compute_volume(info, intent)`:
  - `sl_dist = abs(entry_price - stop_loss)`
  - `loss_per_lot = (sl_dist / tick_size) * tick_value`
  - `risk_money = risk_value` (fixed) ou `balance * risk_value / 100` (percent)
  - `lot = risk_money / loss_per_lot`
  - `normalize_lot(lot, info)`
- `tests/test_executor.py` — adicionar 2 testes de by-risk

**Critérios de aceite:**
- `uv run pytest -q` → ~140 passed

### F5c — Reforço (~2 dias)
**O que implementa:** `InpUseReentry`, `InpReentryContracts`, `InpReentryArmPoints`, `InpReentryTPPoints`, `InpReentrySLPoints`.

**Arquivos a modificar:**
- `src/engine/application/trading_session.py` — `on_tick` checa `_reentry_armed` e preço atual; chama `executor.execute_reentry(...)`
- `src/engine/application/executor.py` — `execute_reentry(symbol, price, is_buy, contracts, tp_points, sl_points)`
- `src/engine/application/poller.py` — distinguir `reentry` de `parcial` no comment
- `tests/test_reentry.py` — NOVO (~5 testes)

**Critérios de aceite:**
- `uv run pytest -q` → ~145 passed

### F5d — Validade por pregões reais (~1 dia)
**O que implementa:** calendário B3 (feriados, dias úteis).

**Arquivos a criar:**
- `src/engine/domain/risk/exchange_calendar.py` — `B3Calendar` (lista de feriados 2026-2027)
- `src/engine/domain/risk/calendar.py` — `TradingWindow` ganha `session_shift(bar_time, now, calendar)`
- `src/engine/domain/strategy/regions.py` — `_is_within_validity` usa `calendar.session_shift()`
- `tests/test_calendar.py` — adicionar 4 testes com feriados

**Critérios de aceite:**
- `uv run pytest -q` → ~149 passed

### F5e — Slippage/spread no simulador (~1 dia)
**O que implementa:** `SimulatedExecutor` ganha `slippage_points`, `spread_points`.

**Arquivos a modificar:**
- `src/engine/application/simulation.py` — `SimulatedExecutor.__init__(preset, slippage_points=0.0, spread_points=0.0)`
- Fill de limite: `entry_price ± slippage` (pior caso)
- Fill de mercado: `ask + slippage` (compra) / `bid - slippage` (venda)
- `tests/test_simulation.py` — adicionar 3 testes com slippage

**Critérios de aceite:**
- `uv run pytest -q` → ~152 passed

### F5f — Multi-estratégia (~3 dias)
**O que implementa:** `Strategy` Protocol, `StrategyRegistry`, cada estratégia tem seu próprio `TradingSession` + `RegionManager` + preset.

**Arquivos a criar:**
- `src/engine/domain/strategy/strategy.py` — `Strategy` (Protocol) + `StrategyConfig`
- `src/engine/application/registry.py` — `StrategyRegistry` (dict name → Strategy)
- `src/engine/cli.py` — `engine run --strategies=A,B` (roda N estratégias em paralelo)
- `tests/test_registry.py` — NOVO (~4 testes)

**Critérios de aceite:**
- `uv run pytest -q` → ~156 passed
- `engine run --strategies=stddev_v510,outra` roda 2 estratégias sem conflito de magic

---

## 6. Roadmap detalhado das fases restantes

### F5 — Multi-estratégia + features completas (~2–3 semanas)

(Detalhado na seção 5.)

---

### F6 — Backtester próprio (~1 mês)

**Objetivo:** rodar backtest sem MT5 (Linux/Mac, paralelizável, customizável).

**Features:**
- `Backtester` que consome CSV/Parquet de candles + ticks
- Slippage realista (spread histórico, latência)
- Suporte a parciais, reforço, by-risk, multi-estratégia
- Exporta equity curve + trades + métricas (Sharpe, drawdown, win rate)
- Compara com Strategy Tester do MT5

**Arquivos a criar:**
- `src/engine/application/backtester.py` — `Backtester` (engine de backtest)
- `src/engine/infrastructure/data/csv_loader.py` — carrega CSV/Parquet
- `src/engine/cli.py` — `engine backtest --from 2026-01-01 --to 2026-12-31`
- `tests/test_backtester.py` — NOVO

**Critérios de aceite:**
- Backtest de 1 ano em < 30s
- Equity curve idêntica ao simulador F2d (mesmo fixture, mesmos parâmetros)

---

## 7. Comandos úteis

```powershell
# Testes
uv run pytest -q                              # suíte completa (~130 passed hoje)
uv run pytest tests/test_golden_v510.py -v    # paridade do detector
uv run pytest tests/test_state.py -v          # persistência
uv run pytest tests/test_run.py -v            # engine run
uv run pytest tests/test_shadow.py -v         # modo sombra

# CLI
uv run engine version
uv run engine check-config                    # audita o preset (7 seções)
uv run engine status --fake                   # detector + gateway sintético
uv run engine status                          # detector + gateway real (MT5 aberto)
uv run engine run --dry-run --fast --max-ticks 10   # loop de teste (não conecta MT5)
uv run engine run --demo --db engine.db       # loop real em demo (MT5 aberto)
uv run engine shadow --ea-magic 20260718 --duration 60   # modo sombra

# Git
git add -A
git commit -m "feat(F4): modo sombra + relatório de divergências (130 passed)"
```

---

## 8. Como o próximo agente deve começar

**Passo 1 — Confirmar estado atual:**
```powershell
uv run pytest -q
```
Deve mostrar **~130 passed**. Se não, **PARE** e investigue o que quebrou antes de
continuar.

**Passo 2 — Ler este `AI.md` inteiro.** Principalmente seções 4 (decisões) e
5 (F5a — parciais, o próximo sub-passo).

**Passo 3 — Rodar `uv run engine check-config`** para confirmar que o preset
carrega (7 seções no log).

**Passo 4 — Começar F5a pelos arquivos novos** (não pelos patches):
1. Criar `src/engine/application/partial_spec.py` (`PartialSpec` dataclass)
2. Criar `tests/test_partials.py` (8 testes com `FakeGateway`)
3. Rodar `uv run pytest tests/test_partials.py -v` → 8 passed
4. **Só então** patchar `intent.py` (`TradeIntent.partials`) + `executor.py` (`place_partial_orders`) + `trading_session.py` (`on_trade_event(PartialFilled)`)
5. Rodar `uv run pytest -q` → ~138 passed

**Passo 5 — Se algo quebrar:**
- Rodar `uv run pytest -q -x` (para no primeiro erro)
- Comparar com `test_golden_v510.py` se for detector, com `test_regions.py` se
  for região, com `test_presets.py` se for config
- **NÃO** consertar teste quebrando código de produção. Se um teste antigo
  quebrou, é bug de F5a, não do teste.

---

## 9. Bugs conhecidos / pontos de atenção

### Bug cosmético — `breakout` logado 2×
Cada teste que chama `_build_intent()` ou `_mk_sessao_com_regiao()` loga `breakout`
2×. **Não é bug**, é o teste chamando helpers 2×. Cosmético.

### `_is_within_validity` usa dias corridos
Aproximação de "pregões anteriores". Refinar em F5d com calendário B3.
**Não é bug**, é TODO.

### `executor._compute_volume` só faz fixed_contracts
`by_risk` retorna `lots_min` (fallback conservador). F5b implementa de verdade.

### `SimulatedExecutor` não implementa parciais
Só SL/TP final. F5a implementa.

### `TradeIntent.volume = 0.0` antes do Executor
O `TradingSession` **não** calcula volume (precisa de `SymbolInfo`). O
`Executor` preenche. **Não é bug**, é decisão de design.

### `OrderResult.is_ok` (não `ok`)
O `OrderResult` tem `@property is_ok`. **Sempre** use `.is_ok` em testes e código.
O `ExecutionResult` do `executor.py` tem **as duas** (`.is_ok` + `.ok` alias) por
retrocompatibilidade.

### `mute_open_min` usa `session.window.start`
O EA usa `InpStartHour` (não a abertura real do pregão). Alinhado com EA.
Se um dia separar "abertura do pregão" de "início operacional", ajustar em F5.

### Datas `naive` vs `aware`
O `FakeGateway.history_deals` normaliza `since` naive → aware UTC. O
`RealMT5Gateway.history_deals` também. Se um dia um método novo receber `datetime`,
**normalize sempre**.

### `engine run` no `--dry-run` cria `engine.db`
O `cmd_run` usa `SqliteStateStore(args.db or "engine.db")` **inclusive** em
`--dry-run`. O teste `test_run_dry_run_max_ticks` resolve isso passando
`db=":memory:"` e fazendo monkeypatch do `SqliteStateStore`. **Não é bug**, é
comportamento intencional (o `--dry-run` deve simular produção).

### `TickInfo` e `symbol_info_tick` (F3d)
- `TickInfo` é um dataclass frozen com `ask`, `bid`, `time` (aware UTC).
- `RealMT5Gateway.symbol_info_tick` usa `mt5.symbol_info_tick(symbol)`.
- `FakeGateway.symbol_info_tick` retorna `171000 ± 50` sintético (determinístico por seed).

### `engine shadow` **coloca ordens reais**
- Não é read-only. O modo sombra **opera** (com `py-magic` diferente do EA).
- Use conta **demo** para testar. Nunca rode na real sem antes validar em demo.
- O `--duration 0` faz o loop não rodar, mas **ainda conecta no MT5** e **ainda
  gera relatório** (com `matched=0`). Útil como smoke test.

### `ShadowComparer` não é idempotente
- Cada chamada a `compare()` gera um `ShadowReport` **novo**.
- Não há estado interno. Se quiser acumular, chame `compare()` com dados diferentes
  e concatene manualmente.

---

## 10. Referências externas

- **EA de referência:** `StdDevVolumeBreakout.mq5` v4.60 (Renan) — não está
  no repositório, mas é a fonte de verdade. Se precisar comparar, pedir ao autor.
- **Indicador companheiro:** `VolumeStdBarPainter.mq5` v3.00 (multi-nível) e
  v1.00 (simples).
- **Script golden:** `z_dump.mq5` — exporta candles + z-score para CSV
  (usado para gerar `tests/fixtures/v510_expected.csv`).
- **Plano completo:** `Plano_Motor_Trading_Python.md` (se existir no repo).
- **README:** `README.md` na raiz (documenta estado atual + roadmap).

---

## 11. Regras de ouro (para a IA que continuar)

1. **Rode `uv run pytest -q` antes e depois de CADA mudança.** Se quebrar,
   reverta imediatamente.
2. **Nunca substitua arquivo inteiro sem antes dar uma olhada na versão atual.**
   O problema mais comum no histórico do projeto foi **colar código novo em cima
   do antigo sem remover**, gerando `SyntaxError` (ex: `from __future__` no
   meio do arquivo, `def` duplicado na mesma linha).
3. **Prefira `Substituir` em vez de `Colar em cima`** quando eu mandar um
   patch de arquivo.
4. **Não mexa em `domain/` sem rodar `test_golden_v510.py` + `test_regions.py`.**
   Esses dois são a fundação.
5. **Não invente campos no preset sem consultar o `.mq5`.** Cada campo tem um
   `# InpXxx` correspondente.
6. **Sempre use `OrderResult.is_ok`** (não `.ok`).
7. **Sempre rode `uv run engine check-config`** depois de mexer no YAML.
8. **Quando em dúvida, pergunte.** O autor tem contexto do EA e sabe quando
   uma mudança quebra paridade.
9. **`ExecutionResult.ok` é alias de `is_ok`** — mantenha as duas properties.
10. **Datas:** sempre `aware UTC` nos métodos públicos. Normalize `since` naive
    para aware antes de comparar.
11. **`engine shadow` coloca ordens reais.** Só rode em demo até validar.
12. **`ShadowComparer` não acessa MT5.** Só `engine shadow` acessa.