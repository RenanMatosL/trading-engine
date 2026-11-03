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
6. **Parciais** (tiers 1/2/3) + breakeven após Tier 1.
7. **Reforço** no retorno à entrada (1x por trade, com TP/SL próprios).
8. **Sizing** fixo ou by-risk (fixed_money / % do balance).
9. **Validade por pregões reais** (calendário B3, feriados 2026-2027).
10. **Multi-estratégia** (N sessões por tick, cada uma com seu magic).

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
| **F6** | Backtester próprio (sem MT5, com slippage realista) | ⏳ **PRÓXIMO** |

**Suíte de testes atual:** **~183 passed** (`uv run pytest -q`).

---

## 3. Arquitetura (mapa de arquivos)

```
src/engine/
├── domain/                          # PURO: zero imports externos
│   ├── shared/
│   │   └── types.py                 # Bar, Side, VolumeSource, MarketSnapshot
│   ├── risk/
│   │   ├── calendar.py              # TradingWindow (+ session_shift)
│   │   └── exchange_calendar.py     # B3Calendar (feriados 2026-2027) — F5d
│   ├── state/
│   │   └── store.py                 # StateStore (Protocol) + SessionSnapshot (F3c + F5e)
│   └── strategy/
│       ├── detector.py              # VolumeStdDetector (paridade EA, F1)
│       ├── location.py              # TradeLocation, RegionState, RegionPhase,
│       │                            #   RegisterResult
│       ├── regions.py               # RegionManager (governança, TTL, validade, rearme)
│       ├── pricing.py               # entry_level / stop_level / take_profit_level
│       │                            #   + PricingConfig + Enums de modo
│       └── strategy.py              # StrategyConfig (F5f)
│
├── config/
│   ├── settings.py                  # EngineSettings (pydantic-settings, .env)
│   └── presets.py                   # StdDevV510Preset (7 seções + validadores cruzados)
│
├── application/                     # orquestração (sem MT5, sem ordens)
│   ├── status.py                    # get_status (F0/F1)
│   ├── intent.py                    # TradeIntent, ReentryIntent, TickDecision, BarResult
│   ├── trading_session.py           # TradingSession (+ state_store + on_trade_event +
│   │                                #   calendar (F5e) + persistência (F5e))
│   ├── events.py                    # EventFeed, BarEvent, TickEvent (F2d)
│   ├── simulation.py                # run_simulation, SimulatedExecutor
│   │                                #   + slippage/spread (F5e)
│   ├── trade_events.py              # EntryFilled, PartialFilled, ReentryFilled,
│   │                                #   ReentryExitFilled, StopLossHit,
│   │                                #   TakeProfitHit, PositionClosed (F3b + F5c)
│   ├── poller.py                    # TradeEventPoller (F3b + F5c)
│   ├── executor.py                  # RealExecutor (+ close_all_at_end_of_day +
│   │                                #   place_partial_orders + place_reentry_*
│   │                                #   + is_stop (F5e))
│   ├── shadow_report.py             # ShadowReport + Divergence (F4)
│   ├── shadow.py                    # ShadowComparer (F4)
│   ├── partial_spec.py              # PartialSpec + make_partial_specs (F5a)
│   └── registry.py                  # StrategyRegistry (F5f)
│
├── infrastructure/
│   ├── mt5/
│   │   ├── gateway.py               # BrokerGateway (Protocol) + RealMT5Gateway
│   │   │                            #   + AccountInfo, SymbolInfo, TickInfo,
│   │   │                            #     PositionInfo, OrderInfo, DealInfo,
│   │   │                            #     OrderRequest (+is_stop em F5e), OrderResult
│   │   └── fake.py                  # FakeGateway (book sintético + _force_fill_pending
│   │                                #   + is_stop em F5e)
│   ├── logging/setup.py             # structlog
│   └── state/
│       ├── memory_store.py          # InMemoryStateStore (F3c)
│       └── sqlite_store.py          # SqliteStateStore + schema (F3c + F5e)
│
└── cli.py                           # engine status | check-config | run | shadow | version
presets/
└── stddev_v510_default.yaml         # todos os inputs do EA v4.60 comentados
tests/
├── fixtures/v510_expected.csv       # 679 candles WIN$N M1 + z-score do MT5
├── test_calendar.py                 # TradingWindow + B3Calendar + session_shift (F5d)
├── test_detector.py
├── test_presets.py                  # bounds + validadores cruzados
├── test_golden_v510.py              # paridade bit-a-bit vs EA v4.60
├── test_regions.py                  # RegionManager + validade por pregões reais
├── test_pricing.py                  # entry/SL/TP + candle grande
├── test_trading_session.py          # filtros + TradeIntent + on_trade_event
├── test_simulation.py               # simulador + slippage/spread (F5e)
├── test_executor.py                 # executor + by-risk + is_stop (F5b/F5e)
├── test_poller.py                   # TradeEventPoller + reentry (F5c)
├── test_state.py                    # StateStore + persistência de parciais/reforço (F5e)
├── test_run.py                      # engine run
├── test_shadow.py                   # modo sombra (F4)
├── test_partials.py                 # parciais + integração (F5a)
├── test_reentry.py                  # reforço (F5c)
└── test_registry.py                 # StrategyRegistry (F5f)
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

### `B3Calendar` (F5d)
- Lista **hardcoded** de feriados 2026-2027. Atualiza uma vez por ano.
- `is_trading_day(d)` — segunda a sexta, exceto feriados.
- `trading_days_between(start, end)` — conta pregões (negativo se `start > end`).
- **Não** move feriados que caem em fim de semana.
- **TODO F6:** atualizar feriados 2028+.

### `TradingWindow.session_shift(bar_time, now, calendar)`
- Retorna `calendar.trading_days_between(bar_time.date(), now.date())`.
- Se `calendar is None`, fallback para **dias corridos** (comportamento antigo).
- **Não** usa `start`/`end` do `TradingWindow` (só `bar_time` e `now`).
- **TODO F6:** transformar em `@staticmethod` (elimina o `TradingWindow(start=time(0,0), end=time(0,0))` feio no `regions.py`).

### `RegionManager`
- Fila `dict[bar_time, RegionState]`, limite `max_loc=12` (paridade com EA).
- Fila cheia substitui a de **menor volume** (governança por volume).
- `RegionPhase` é **enum explícito** (WAITING_BREAKOUT / BROKEN / CONSUMED / REARMED).
  **Não** use flags booleanas — gera estados impossíveis.
- **NÃO** aplica filtros de sessão (isso é `TradingSession`).
- **F5d:** `__init__` aceita `calendar: B3Calendar | None = None`. Se presente, `_is_within_validity` usa `session_shift`. Se `None`, fallback para dias corridos.
- **F5e:** o `TradingSession` **passa** `B3Calendar()` por default (integração concluída).

### `TradingSession`
- **Não** executa ordens. **Não** consulta MT5.
- Emite `TradeIntent` (frozen) — o `Executor` executa.
- Filtros de sessão em `on_tick`: horário, entry_block, cooldown, daily_limit, carry_delay.
- Filtro de abertura (`mute_open_min`) em `on_bar_closed`.
- Estado: `_last_sl_time`, `_trades_today`, `_current_day`, `_current_entry_region`, `_current_entry_position`, `_current_entry_price`, `_current_is_buy`, `_partials_filled`, `_reentry_armed`, `_reentry_done`.
- **F3b:** `on_trade_event(event, now)` consome `TradeEvent` do poller:
  - `EntryFilled` → rastreia `_current_entry_position`
  - `StopLossHit` → `notify_stop_loss` + rearme/consume da região (decidido por `use_reverse`/`reuse_sl_signal`)
  - `TakeProfitHit` / `PositionClosed` → consome a região
  - `PartialFilled` → **F5a:** rastreia tier via `_infer_tier_from_comment` + adiciona a `_partials_filled`
  - `ReentryFilled` / `ReentryExitFilled` → **F5c:** apenas loga (o `engine run` já armou TP/SL)
- **F3c:** `state_store` opcional no `__init__`. `save_state()` serializa (snapshot + regiões), `_load_state()` desserializa. **Todas as mutações chamam `save_state()`** (no-op se `state_store is None`).
- **F5a:** `notify_trade_opened` e `notify_position_closed` **zeram** `_partials_filled`.
- **F5c:** `notify_trade_opened(now, region_bar_time, entry_price, is_buy)` grava `_current_entry_price` e `_current_is_buy`; `_maybe_reentry(snapshot)` detecta quando armar (`reentry_armed`) e quando disparar (`ReentryIntent`). `_reentry_done` evita rearmar 2x.
- **F5e:** `__init__` aceita `calendar: B3Calendar | None = None`. Se `None`, cria `B3Calendar()` por default. O `RegionManager` recebe o calendar. `SessionSnapshot` agora inclui 5 campos extras (persistência de parciais/reforço).
- **F5f:** o `cmd_run` cria **N** `TradingSession` (uma por estratégia no `StrategyRegistry`).

### `TradeIntent`
- `volume` = 0.0 até o `Executor` preencher (com `SymbolInfo`).
- `as_pending=True` → Executor usa BuyLimit/SellLimit.
- `as_pending=False` → Executor usa Buy/Sell (a mercado).
- **F5a:** `partials: tuple[PartialSpec, ...] | None`. `None` quando `use_partial_exit=False`.

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
- `make_partial_specs(...)` traduz do preset. Tier 1 usa `partial_points`/`partial_percent` global (não `tier.points`).

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
- `RealMT5Gateway`: import tardio (`import MetaTrader5 as mt5` dentro do método).
- `FakeGateway`: book sintético para desenvolvimento/testes em qualquer SO.
- **IMPORTANTE:** o `OrderResult` tem `@property is_ok` (não `ok`). O `ExecutionResult` do `executor.py` tem **as duas** (`.is_ok` + `.ok`, alias retrocompatível).
- **F3d:** `TickInfo` (dataclass) + `symbol_info_tick(symbol)` no Protocol e nas duas implementações.
- **F5e:** `OrderRequest.is_stop: bool = False`. O `RealMT5Gateway` usa `ORDER_TYPE_BUY_STOP`/`SELL_STOP`. O `FakeGateway` usa `is_stop` (sem string).

### `StateStore` (F3c + F5e)
- `StateStore` é **Protocol** (domínio puro). Implementações em `infrastructure/state/`.
- `SessionSnapshot` é `frozen` e serializável (10 campos: `last_sl_time`, `trades_today`, `current_day`, `current_entry_region`, `current_entry_position`, `current_entry_price`, `current_is_buy`, `reentry_armed`, `reentry_done`, `partials_filled`).
- **F5e:** persiste parciais/reforço entre reinícios.
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

### `TradeEventPoller` (F3b + F5c)
- Estado: `_last_deal_ticket` (idempotência).
- A cada `poll()`: lê `history_deals(since, symbol, magic)`, filtra `ticket > _last_deal_ticket`, classifica via `_classify_deal`, atualiza `_last_deal_ticket`.
- 7 tipos de evento (F3b: 5, F5c: +2):
  - `EntryFilled`, `PartialFilled`, `StopLossHit`, `TakeProfitHit`, `PositionClosed`
  - `ReentryFilled` (comment `engine_reentry`)
  - `ReentryExitFilled` (comment `engine_reentry_tp` ou `engine_reentry_sl`)

### `engine run` (F3d + F5a + F5c + F5f)
- Subcomando `run` no `cli.py`.
- Flags: `--dry-run` (FakeGateway), `--demo` (RealMT5Gateway), `--preset`, `--db` (default `engine.db`), `--poll-interval` (default `1.0`), `--max-ticks` (0 = infinito), `--fast` (não dorme), **`--strategies=A,B` (F5f)**.
- **F5f:** o `cmd_run` cria **N** sessões (uma por estratégia no `StrategyRegistry`). O loop principal itera **N sessões por tick** (todas processam o mesmo `snapshot`).
- Loop (por sessão): `on_tick` → `execute` → parciais/reentry → `poller.poll` → `on_trade_event`. Fim do dia: `close_all_at_end_of_day`. `save_state()`.
- **F5a:** após `executor.execute(intent)` OK, chama `executor.place_partial_orders(intent, symbol)` se `intent.partials` existe. Após `PartialFilled` de Tier 1, move SL para breakeven (se `breakeven_after_partial=True`), 1x por trade.
- **F5c:** após `decision.reentry_intent`, chama `executor.place_reentry_order(...)` e guarda `pending_reentry`. No `ReentryFilled`, chama `executor.place_reentry_exits(...)` e zera `pending_reentry`.
- `KeyboardInterrupt` → `save_state()` (de cada sessão) + `close()` (de cada store) + `gw.shutdown()`.

### `engine shadow` (F4)
- Subcomando `shadow` no `cli.py`.
- Flags: `--ea-magic` (obrigatório), `--py-magic` (default 0), `--duration` (min, default 60), `--poll-interval` (default 2.0), `--tolerance-points` (default 2.0), `--report-dir` (default `reports/`), `--db` (default `engine_shadow.db`), `--preset`.
- Loop similar ao `engine run`, mas guarda `py_trades` (lista de `TradeIntent`) e, ao fim, lê `history_deals` do EA (magic dele) e chama `ShadowComparer.compare`.
- **F5a:** também chama `executor.place_partial_orders(intent, symbol)` quando há parciais.
- **Coloca ordens reais no MT5** (com o `py-magic`). Não é read-only.
- **Requer MT5 aberto.** Não funciona com `--dry-run`.

### Sizing (F5b)
- `_compute_volume(info, intent)`:
  - **FIXED_CONTRACTS:** `total_contracts * lot_per_contract` normalizado.
  - **BY_RISK:** `risk_money / loss_per_lot`, onde:
    - `sl_dist = abs(entry - stop_loss)`
    - `loss_per_lot = (sl_dist / tick_size) * tick_value`
    - `risk_money = risk_value` (fixed_money) ou `balance * risk_value / 100` (percent_balance)
  - `total_contracts` é **ignorado** em by-risk.
  - `risk_value=0` ou `sl_dist=0` → `lots_min` (fallback).
  - `_compute_risk_money(risk, gateway)` chama `gateway.account().balance` para percent.

### Simulador (F2d + F5e)
- SL **ganha empate** dentro do mesmo tick (conservador, MT5-style).
- Parciais: **não implementadas no simulador ainda** (F5a cobriu `RealExecutor`).
- Volume = fixed_contracts (by-risk só em `RealExecutor`).
- **F5e:** `SimulatedExecutor.__init__(preset, slippage_points=0.0, spread_points=0.0)`. Slippage aplicado no fill (pior caso). `spread_points` reservado para F6 (backtester próprio).

### `FakeGateway.place_order` — `is_stop` explícito (F5e)
- **Não** detecta mais por string. Usa `req.is_stop` (campo do `OrderRequest`).
- `is_stop=True` → registra ordem pendente (não abre posição).
- `is_limit=True` → registra ordem pendente.
- Senão → market (abre posição).

### Coisas que **NÃO podem ser quebradas**
1. `test_golden_v510.py` — paridade bit-a-bit com EA. **Sagrado.**
2. `test_regions.py` — semântica do `RegionManager` + validade por pregões. **Sagrado.**
3. `test_presets.py` — validadores cruzados. **Sagrado.**
4. `test_pricing.py` — fórmulas de entry/SL/TP. **Sagrado.**
5. `test_simulation.py` — semântica de SL/TP no simulador + slippage. **Sagrado.**
6. `test_executor.py` — place/cancel/modify/close + by-risk + is_stop. **Sagrado.**
7. `test_poller.py` — classificação de deals + reentry. **Sagrado.**
8. `test_trading_session.py` — filtros + on_trade_event. **Sagrado.**
9. `test_state.py` — persistência + parciais/reforço. **Sagrado.**
10. `test_run.py` — engine run. **Sagrado.**
11. `test_shadow.py` — ShadowComparer. **Sagrado.**
12. `test_partials.py` — PartialSpec + integração. **Sagrado.**
13. `test_reentry.py` — `_maybe_reentry` + `place_reentry_*`. **Sagrado.**
14. `test_calendar.py` — `TradingWindow` + `B3Calendar` + `session_shift`. **Sagrado.**
15. `test_registry.py` — `StrategyConfig` + `StrategyRegistry`. **Sagrado.**

Antes de qualquer mudança, **rode `uv run pytest -q`** e confirme que continua ~183 passed.

---

## 5. Próximo passo: F6 — Backtester próprio

**Objetivo:** rodar backtest **sem MT5** (Linux/Mac, paralelizável, customizável).

**O problema que F6 resolve:**
Hoje, o backtest é feito no **Strategy Tester do MT5** (via `.mq5`). Isso funciona, mas:
- Só roda em Windows.
- Não paraleliza.
- Não permite customizar slippage/spread.
- Não exporta equity curve/trades em formato próprio.
- Não suporta multi-estratégia em backtest.

**Arquitetura:**

```
src/engine/application/
├── backtester.py            # NOVO: Backtester (engine de backtest)
└── metrics.py               # NOVO: Sharpe, drawdown, win rate, etc

src/engine/infrastructure/data/
└── csv_loader.py            # NOVO: carrega CSV/Parquet de candles + ticks

src/engine/cli.py            # patch: engine backtest --from YYYY-MM-DD --to YYYY-MM-DD

tests/
└── test_backtester.py       # NOVO: ~6 testes
```

**Componentes:**

1. **`Backtester`** — orquestra:
   - Consome `list[Bar]` + `list[MarketSnapshot]` (via `csv_loader`).
   - Reusa `TradingSession` + `SimulatedExecutor` (F2d + F5e).
   - Roda `EventFeed` (F2d).
   - Retorna `SimulationResult` (trades + equity + stats).
   - **Compara** com `SimulationResult` de outro backtest (ex: MT5 Strategy Tester).

2. **`csv_loader`** — carrega CSV com candles (time, open, high, low, close, tick_volume, real_volume). **TODO F6:** suportar Parquet (precisa `pandas`/`pyarrow`).

3. **`metrics`** — calcula:
   - Sharpe ratio
   - Max drawdown
   - Win rate
   - Profit factor
   - Average win / average loss
   - Total return

4. **`engine backtest --from YYYY-MM-DD --to YYYY-MM-DD`** — CLI.

**Decisões já tomadas para F6:**
1. `Backtester` reusa `SimulatedExecutor` (F2d + F5e). **Não** duplica lógica.
2. `EventFeed` (F2d) é o motor. `Backtester` só **constrói** o feed a partir do CSV.
3. Métricas em `metrics.py` (funções puras, sem estado).
4. CLI: `engine backtest --from YYYY-MM-DD --to YYYY-MM-DD [--preset PATH] [--csv PATH]`.
5. **Não** suporta parciais/reforço no backtest na primeira versão (o `SimulatedExecutor` não tem). **TODO F6+.**

**Arquivos a criar em F6:**

| Arquivo | Ação |
|---|---|
| `src/engine/infrastructure/data/csv_loader.py` | criar |
| `src/engine/application/metrics.py` | criar |
| `src/engine/application/backtester.py` | criar |
| `src/engine/cli.py` | patch (`cmd_backtest`) |
| `tests/test_backtester.py` | criar (~6 testes) |

**Critérios de aceite de F6:**
- `uv run pytest tests/test_backtester.py -v` → **~6 passed**
- `uv run pytest -q` → **~189 passed**
- Backtest de 1 ano em < 30s.
- Equity curve idêntica ao simulador F2d (mesmo fixture, mesmos parâmetros).

---

## 6. Roadmap detalhado das fases restantes

### F6 — Backtester próprio (~25-30h)

(Detalhado na seção 5.)

---

## 7. Comandos úteis

```powershell
# Testes
uv run pytest -q                              # suíte completa (~183 passed hoje)
uv run pytest tests/test_golden_v510.py -v    # paridade do detector
uv run pytest tests/test_calendar.py -v       # calendário B3
uv run pytest tests/test_state.py -v          # persistência + parciais/reforço
uv run pytest tests/test_run.py -v            # engine run
uv run pytest tests/test_shadow.py -v         # modo sombra
uv run pytest tests/test_partials.py -v       # parciais
uv run pytest tests/test_reentry.py -v        # reforço
uv run pytest tests/test_registry.py -v       # multi-estratégia

# CLI
uv run engine version
uv run engine check-config                    # audita o preset (7 seções)
uv run engine status --fake                   # detector + gateway sintético
uv run engine status                          # detector + gateway real (MT5 aberto)
uv run engine run --dry-run --fast --max-ticks 10   # loop de teste (não conecta MT5)
uv run engine run --dry-run --fast --max-ticks 3 --strategies=stddev_v510  # multi-estratégia
uv run engine run --demo --db engine.db       # loop real em demo (MT5 aberto)
uv run engine shadow --ea-magic 20260718 --duration 60   # modo sombra

# Git
git add -A
git commit -m "feat(F5f): multi-estratégia (183 passed)"
```

---

## 8. Como o próximo agente deve começar

**Passo 1 — Confirmar estado atual:**
```powershell
uv run pytest -q
```
Deve mostrar **~183 passed**. Se não, **PARE** e investigue o que quebrou antes de
continuar.

**Passo 2 — Ler este `AI.md` inteiro.** Principalmente seções 4 (decisões) e
5 (F6 — backtester próprio).

**Passo 3 — Rodar `uv run engine check-config`** para confirmar que o preset
carrega (7 seções no log).

**Passo 4 — Começar F6 pelos arquivos novos:**
1. Criar `src/engine/infrastructure/data/csv_loader.py` (`load_bars_csv`).
2. Criar `src/engine/application/metrics.py` (`sharpe`, `max_drawdown`, `win_rate`, etc).
3. Criar `src/engine/application/backtester.py` (`Backtester.run`).
4. Criar `tests/test_backtester.py` (6 testes com CSV sintético).
5. Rodar `uv run pytest tests/test_backtester.py -v` → 6 passed.
6. **Só então** patchar `cli.py` (`cmd_backtest`).
7. Rodar `uv run pytest -q` → ~189 passed.

**Passo 5 — Se algo quebrar:**
- Rodar `uv run pytest -q -x` (para no primeiro erro)
- Comparar com `test_golden_v510.py` se for detector, com `test_regions.py` se
  for região, com `test_presets.py` se for config
- **NÃO** consertar teste quebrando código de produção. Se um teste antigo
  quebrou, é bug de F6, não do teste.

---

## 9. Bugs conhecidos / pontos de atenção

### Bug cosmético — `breakout` logado 2×
Cada teste que chama `_build_intent()` ou `_mk_sessao_com_regiao()` loga `breakout`
2×. **Não é bug**, é o teste chamando helpers 2×. Cosmético.

### `_is_within_validity` — resolvido em F5e
O `TradingSession` agora passa `B3Calendar()` por default no `RegionManager`.
A validade usa pregões reais. **Não é mais bug.**

### `session_shift` usa `TradingWindow(start=time(0,0), end=time(0,0))`
Gambiarra para não precisar mudar a assinatura. **TODO F6:** transformar em `@staticmethod`.

### `FakeGateway` — `is_stop` explícito (F5e)
Não detecta mais por string. Usa `req.is_stop`. **Não é mais bug.**

### `SessionSnapshot` persiste parciais/reforço (F5e)
O `_current_entry_price`, `_current_is_buy`, `_reentry_armed`, `_reentry_done`, `_partials_filled` **são salvos** no `save_state()`. **Não é mais bug.**

### `SimulatedExecutor` não implementa parciais
Só SL/TP final. **TODO F6+.**

### `SimulatedExecutor` slippage/spread (F5e)
Slippage aplicado no fill. Spread reservado para F6.

### `StrategyRegistry` registra 1 estratégia com `magic=0`
Hoje só tem 1 preset. Se registrar 2, precisa `magic` diferente. **TODO F6+:** ler magic de config externa.

### `TradeIntent.volume = 0.0` antes do Executor
O `TradingSession` **não** calcula volume (precisa de `SymbolInfo`). O
`Executor` preenche. **Não é bug**, é decisão de design.

### `OrderResult.is_ok` (não `ok`)
O `OrderResult` tem `@property is_ok`. **Sempre** use `.is_ok` em testes e código.
O `ExecutionResult` do `executor.py` tem **as duas** (`.is_ok` + `.ok` alias) por
retrocompatibilidade.

### `mute_open_min` usa `session.window.start`
O EA usa `InpStartHour` (não a abertura real do pregão). Alinhado com EA.
Se um dia separar "abertura do pregão" de "início operacional", ajustar em F6.

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

### Parciais: `place_partial_orders` chama `symbol_info` de novo
- `place_partial_orders` chama `self._gw.symbol_info(symbol)` para normalizar lotes.
- Poderia reusar o `info` de `execute()`, mas para simplicidade chama de novo.
- **Não é bug**, é decisão de design.

### `_infer_tier_from_comment` depende do comment `engine_partial_N`
- O `Poller` classifica como `PartialFilled` se `"partial" in comment.lower()`.
- O `TradingSession._infer_tier_from_comment` extrai o `N` do `partial_N`.
- Se o `Executor` mudar o formato do comment, os dois quebram juntos.

### Reforço: `place_reentry_exits` usa `comment="engine_reentry_sl"` e `is_stop=True`
- O `FakeGateway` usa `is_stop` (F5e).
- O `Poller` classifica como `ReentryExitFilled` por `"reentry_sl"` no comment.
- Se o `Executor` mudar o comment, os dois quebram juntos.

### Multi-estratégia: `--strategies` e `preset.strategy`
- O `cmd_run` registra o preset principal com `name = preset.strategy` (não `preset.name`).
- `preset.strategy` = tipo (`stddev_v510`), `preset.name` = preset (`v510_default`).
- `--strategies=A,B` usa `preset.strategy`. **TODO F6+:** aceitar `preset.name` também.

### `StrategyRegistry` só tem 1 estratégia registrada
- Hoje só tem 1 preset. Para 2+, precisa registrar 2 `StrategyConfig` com `magic` diferentes.
- **TODO F6+:** carregar múltiplos presets.

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
13. **Parciais no `Poller`:** o comment do `Executor` é `engine_partial_N`. Se
    mudar, o `Poller` e o `TradingSession` quebram juntos.
14. **Reforço no `Poller`:** o comment do `Executor` é `engine_reentry` (entrada)
    e `engine_reentry_tp`/`engine_reentry_sl` (saídas). O `is_stop` do `OrderRequest`
    é `True` no SL.
15. **Calendário B3:** `B3Calendar` tem feriados hardcoded 2026-2027. Se rodar
    em 2028+, adicione à lista.
16. **`session_shift`:** usa `TradingWindow(start=time(0,0), end=time(0,0))` —
    gambiarra. F6 transforma em `@staticmethod`.
17. **Multi-estratégia:** `--strategies` usa `preset.strategy` (não `preset.name`). Se registrar 2 presets, precisa `magic` diferentes.
18. **F5 está 100% completo** (a, b, c, d, e, f). **F6 (backtester próprio) é o último grande.**