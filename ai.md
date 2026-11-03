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
| **F5e** | Slippage/spread no simulador + correções pendentes | ⏳ **PRÓXIMO** |
| **F5f** | Multi-estratégia (`Strategy` Protocol + `StrategyRegistry`) | ⏳ pendente |
| **F6** | Backtester próprio (sem MT5, com slippage realista) | ⏳ pendente |

**Suíte de testes atual:** **~167 passed** (`uv run pytest -q`).

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
│   ├── intent.py                    # TradeIntent, ReentryIntent, TickDecision, BarResult
│   ├── trading_session.py           # TradingSession (+ state_store + on_trade_event)
│   ├── events.py                    # EventFeed, BarEvent, TickEvent (F2d)
│   ├── simulation.py                # run_simulation, SimulatedExecutor (F2d)
│   ├── trade_events.py              # EntryFilled, PartialFilled, ReentryFilled,
│   │                                #   ReentryExitFilled, StopLossHit,
│   │                                #   TakeProfitHit, PositionClosed (F3b + F5c)
│   ├── poller.py                    # TradeEventPoller (F3b + F5c)
│   ├── executor.py                  # RealExecutor (+ close_all_at_end_of_day +
│   │                                #   place_partial_orders + place_reentry_*)
│   ├── shadow_report.py             # ShadowReport + Divergence (F4)
│   ├── shadow.py                    # ShadowComparer (F4)
│   └── partial_spec.py              # PartialSpec + make_partial_specs (F5a)
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
├── test_calendar.py                 # TradingWindow + B3Calendar + session_shift (F5d)
├── test_detector.py
├── test_presets.py                  # bounds + validadores cruzados
├── test_golden_v510.py              # paridade bit-a-bit vs EA v4.60
├── test_regions.py                  # RegionManager (+ validade por pregões reais)
├── test_pricing.py                  # entry/SL/TP + candle grande
├── test_trading_session.py          # filtros + TradeIntent + on_trade_event
├── test_simulation.py               # simulador
├── test_executor.py                 # executor (place/cancel/modify/close + by-risk)
├── test_poller.py                   # TradeEventPoller (+ reentry)
├── test_state.py                    # StateStore + persistência
├── test_run.py                      # engine run
├── test_shadow.py                   # modo sombra (F4)
├── test_partials.py                 # parciais + integração (F5a)
└── test_reentry.py                  # reforço (F5c)
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
- `Feriados 2026`: 1/1, 16-17/2 (Carnaval), 3/4 (Sexta-Santa), 21/4, 1/5, 4/6 (Corpus Christi), 7/9, 12/10, 2/11, 15/11, 20/11 (Consciência Negra), 25/12.
- `Feriados 2027`: 1/1, 8-9/2 (Carnaval), 26/3 (Sexta-Santa), 21/4, 1/5, 27/5 (Corpus Christi), 7/9, 12/10, 2/11, 15/11, 20/11, 25/12.

### `TradingWindow.session_shift(bar_time, now, calendar)`
- Retorna `calendar.trading_days_between(bar_time.date(), now.date())`.
- Se `calendar is None`, fallback para **dias corridos** (comportamento antigo).
- **Não** usa `start`/`end` do `TradingWindow` (só `bar_time` e `now`).
- **TODO F5e:** transformar em `@staticmethod` (elimina o `TradingWindow(start=time(0,0), end=time(0,0))` feio no `regions.py`).

### `RegionManager`
- Fila `dict[bar_time, RegionState]`, limite `max_loc=12` (paridade com EA).
- Fila cheia substitui a de **menor volume** (governança por volume).
- `RegionPhase` é **enum explícito** (WAITING_BREAKOUT / BROKEN / CONSUMED / REARMED).
  **Não** use flags booleanas — gera estados impossíveis.
- **NÃO** aplica filtros de sessão (isso é `TradingSession`).
- **F5d:** `__init__` aceita `calendar: B3Calendar | None = None`. Se presente, `_is_within_validity` usa `session_shift`. Se `None`, fallback para dias corridos.
- **⚠️ Pendência:** o `TradingSession` **não** passa `calendar=B3Calendar()` no `RegionManager`. Em produção, `_is_within_validity` continua usando dias corridos. **TODO F5e:** integrar.

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

### `BrokerGateway` (Protocol) + ACL
- Domínio **nunca** importa `MetaTrader5`. Sempre conversa com o Protocol.
- `RealMT5Gateway`: import tardio (`import MetaTrader5 as mt5` dentro do método).
- `FakeGateway`: book sintético para desenvolvimento/testes em qualquer SO.
- **IMPORTANTE:** o `OrderResult` tem `@property is_ok` (não `ok`). O `ExecutionResult` do `executor.py` tem **as duas** (`.is_ok` + `.ok`, alias retrocompatível).
- **F3d:** `TickInfo` (dataclass) + `symbol_info_tick(symbol)` no Protocol e nas duas implementações.

### `StateStore` (F3c)
- `StateStore` é **Protocol** (domínio puro). Implementações em `infrastructure/state/`.
- `SessionSnapshot` é `frozen` e serializável (5 campos: `last_sl_time`, `trades_today`, `current_day`, `current_entry_region`, `current_entry_position`).
- **Não persiste** `_current_entry_price`, `_current_is_buy`, `_reentry_armed`, `_reentry_done`, `_partials_filled` (F5a/F5c). Em reinício no meio de trade, esses estados são perdidos. **TODO F5e.**
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

### `engine run` (F3d + F5a + F5c)
- Subcomando `run` no `cli.py`.
- Flags: `--dry-run` (FakeGateway), `--demo` (RealMT5Gateway), `--preset`, `--db` (default `engine.db`), `--poll-interval` (default `1.0`), `--max-ticks` (0 = infinito), `--fast` (não dorme).
- Loop: tick → snapshot → on_tick → executor; poller; new bar → on_bar_closed; fim do dia (close_outside) → close_all_at_end_of_day; save_state.
- **F5a:** após `executor.execute(intent)` OK, chama `executor.place_partial_orders(intent, symbol)` se `intent.partials` existe. Após `PartialFilled` de Tier 1, move SL para breakeven (se `breakeven_after_partial=True`), 1x por trade.
- **F5c:** após `decision.reentry_intent`, chama `executor.place_reentry_order(...)` e guarda `pending_reentry`. No `ReentryFilled`, chama `executor.place_reentry_exits(...)` e zera `pending_reentry`.
- `KeyboardInterrupt` → save_state + shutdown.

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

### Simulador (F2d)
- SL **ganha empate** dentro do mesmo tick (conservador, MT5-style).
- Parciais: **não implementadas no simulador ainda** (F5a cobriu `RealExecutor`; simular parciais no `SimulatedExecutor` fica para F5e).
- Volume = fixed_contracts (by-risk só em `RealExecutor`).
- Slippage/spread: **não implementados** (F5e).

### `FakeGateway.place_order` — `is_stop` por comment (F5c)
- Detecta stop por string: `not is_limit and ("sl" in comment or "stop" in comment)`.
- **Frágil** — depende do comment `engine_reentry_sl`.
- **TODO F5e:** adicionar campo `is_stop: bool` no `OrderRequest` (elimina a detecção por string).

### Coisas que **NÃO podem ser quebradas**
1. `test_golden_v510.py` — paridade bit-a-bit com EA. **Sagrado.**
2. `test_regions.py` — semântica do `RegionManager` + validade por pregões. **Sagrado.**
3. `test_presets.py` — validadores cruzados. **Sagrado.**
4. `test_pricing.py` — fórmulas de entry/SL/TP. **Sagrado.**
5. `test_simulation.py` — semântica de SL/TP no simulador. **Sagrado.**
6. `test_executor.py` — place/cancel/modify/close + by-risk. **Sagrado.**
7. `test_poller.py` — classificação de deals + reentry. **Sagrado.**
8. `test_trading_session.py` — filtros + on_trade_event. **Sagrado.**
9. `test_state.py` — persistência. **Sagrado.**
10. `test_run.py` — engine run. **Sagrado.**
11. `test_shadow.py` — ShadowComparer. **Sagrado.**
12. `test_partials.py` — PartialSpec + integração. **Sagrado.**
13. `test_reentry.py` — `_maybe_reentry` + `place_reentry_*`. **Sagrado.**
14. `test_calendar.py` — `TradingWindow` + `B3Calendar` + `session_shift`. **Sagrado.**

Antes de qualquer mudança, **rode `uv run pytest -q`** e confirme que continua ~167 passed.

---

## 5. Próximo passo: F5e — Slippage/spread + correções pendentes

**Objetivo:** implementar slippage/spread no simulador **e** fechar 3 TODOs acumulados.

**Escopo (3 partes):**

### Parte 1 — Slippage/spread no simulador (obrigatório)

`SimulatedExecutor` ganha `slippage_points` e `spread_points`:
- **Fill de limite:** `entry_price ± slippage` (pior caso)
- **Fill de mercado:** `ask + slippage` (compra) / `bid - slippage` (venda)
- **Spread:** `MarketSnapshot.spread` já existe, mas o simulador ignora.

**Arquivos:**
- `src/engine/application/simulation.py` — `SimulatedExecutor.__init__(preset, slippage_points=0.0, spread_points=0.0)`
- `tests/test_simulation.py` — +3 testes com slippage

### Parte 2 — `OrderRequest.is_stop` (recomendado)

Hoje o `FakeGateway.place_order` detecta stop por `"sl" in comment`. **Frágil.**

**Fix:** adicionar `is_stop: bool = False` no `OrderRequest`. O `RealMT5Gateway` usa `ORDER_TYPE_BUY_STOP`/`SELL_STOP`. O `RealExecutor.place_reentry_exits` passa `is_stop=True` no SL.

**Arquivos:**
- `src/engine/infrastructure/mt5/gateway.py` — `OrderRequest.is_stop`
- `src/engine/infrastructure/mt5/fake.py` — usa `is_stop` (sem string)
- `src/engine/infrastructure/mt5/gateway.py` (Real) — trata `is_stop`
- `src/engine/application/executor.py` — passa `is_stop=True` no SL

### Parte 3 — Integração do calendar no `TradingSession` + persistência de parciais/reforço

**3a. Calendar no `TradingSession`:**
- `TradingSession.__init__` ganha `calendar: B3Calendar | None = None`
- Se `None`, cria `B3Calendar()` por default (produção)
- O `RegionManager` recebe o calendar
- O `engine run` e `engine shadow` podem passar `calendar` explicitamente

**3b. Persistência de parciais/reforço:**
- `SessionSnapshot` ganha 5 campos: `current_entry_price`, `current_is_buy`, `reentry_armed`, `reentry_done`, `partials_filled`
- `save_state()` / `_load_state()` serializam/desserializam
- Schema SQLite ganha colunas (migração via `ALTER TABLE`)

**Arquivos (parte 3):**
- `src/engine/domain/state/store.py` — `SessionSnapshot` +5 campos
- `src/engine/application/trading_session.py` — `calendar` no `__init__` + persistência
- `src/engine/infrastructure/state/sqlite_store.py` — schema + serialização
- `src/engine/infrastructure/state/memory_store.py` — nada (já funciona com dataclass)

**Critérios de aceite de F5e:**
- `uv run pytest -q` → **~172 passed** (167 + 5: 3 slippage + 2 novos de `is_stop`/calendar)
- `test_golden_v510.py`, `test_regions.py`, `test_pricing.py`, `test_simulation.py` continuam verdes.

---

## 6. Roadmap detalhado das fases restantes

### F5e — Slippage/spread + correções (~4-6h)

(Detalhado na seção 5.)

---

### F5f — Multi-estratégia (~8-10h)

**O que implementa:** `Strategy` Protocol, `StrategyRegistry`, cada estratégia tem seu próprio `TradingSession` + `RegionManager` + preset.

**Arquivos:**
- `src/engine/domain/strategy/strategy.py` — NOVO, `Strategy` (Protocol) + `StrategyConfig`.
- `src/engine/application/registry.py` — NOVO, `StrategyRegistry` (dict name → Strategy).
- `src/engine/cli.py` — `engine run --strategies=A,B` (roda N estratégias em paralelo).
- `tests/test_registry.py` — NOVO (~4 testes).

**Critérios de aceite:**
- `uv run pytest -q` → ~176 passed.
- `engine run --strategies=stddev_v510,outra` roda 2 estratégias sem conflito de magic.

---

### F6 — Backtester próprio (~25-30h)

**Objetivo:** rodar backtest sem MT5 (Linux/Mac, paralelizável, customizável).

**Features:**
- `Backtester` que consome CSV/Parquet de candles + ticks.
- Slippage realista (spread histórico, latência).
- Suporte a parciais, reforço, by-risk, multi-estratégia.
- Exporta equity curve + trades + métricas (Sharpe, drawdown, win rate).
- Compara com Strategy Tester do MT5.

**Arquivos a criar:**
- `src/engine/application/backtester.py` — NOVO.
- `src/engine/infrastructure/data/csv_loader.py` — NOVO.
- `src/engine/application/metrics.py` — NOVO (Sharpe, drawdown, etc).
- `src/engine/cli.py` — `engine backtest --from 2026-01-01 --to 2026-12-31`.
- `tests/test_backtester.py` — NOVO.

**Critérios de aceite:**
- Backtest de 1 ano em < 30s.
- Equity curve idêntica ao simulador F2d (mesmo fixture, mesmos parâmetros).

---

## 7. Comandos úteis

```powershell
# Testes
uv run pytest -q                              # suíte completa (~167 passed hoje)
uv run pytest tests/test_golden_v510.py -v    # paridade do detector
uv run pytest tests/test_calendar.py -v       # calendário B3 (F5d)
uv run pytest tests/test_state.py -v          # persistência
uv run pytest tests/test_run.py -v            # engine run
uv run pytest tests/test_shadow.py -v         # modo sombra
uv run pytest tests/test_partials.py -v       # parciais (F5a)
uv run pytest tests/test_reentry.py -v        # reforço (F5c)

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
git commit -m "feat(F5d): B3Calendar + validade por pregões reais (167 passed)"
```

---

## 8. Como o próximo agente deve começar

**Passo 1 — Confirmar estado atual:**
```powershell
uv run pytest -q
```
Deve mostrar **~167 passed**. Se não, **PARE** e investigue o que quebrou antes de
continuar.

**Passo 2 — Ler este `AI.md` inteiro.** Principalmente seções 4 (decisões) e
5 (F5e — slippage/spread + correções).

**Passo 3 — Rodar `uv run engine check-config`** para confirmar que o preset
carrega (7 seções no log).

**Passo 4 — Começar F5e pela parte 1 (slippage/spread):**
1. Patch `src/engine/application/simulation.py` — `SimulatedExecutor.__init__(slippage_points, spread_points)`.
2. Patch `tests/test_simulation.py` — +3 testes com slippage.
3. Rodar `uv run pytest tests/test_simulation.py -v` → 10 passed.
4. Rodar `uv run pytest -q` → ~170 passed.

**Passo 5 — Parte 2 (`is_stop`):**
1. Patch `src/engine/infrastructure/mt5/gateway.py` — `OrderRequest.is_stop`.
2. Patch `src/engine/infrastructure/mt5/fake.py` — usa `is_stop` (sem string).
3. Patch `src/engine/infrastructure/mt5/gateway.py` (Real) — trata `is_stop`.
4. Patch `src/engine/application/executor.py` — passa `is_stop=True` no SL.
5. Rodar `uv run pytest -q` → ~170 passed.

**Passo 6 — Parte 3 (calendar + persistência):**
1. Patch `src/engine/domain/state/store.py` — `SessionSnapshot` +5 campos.
2. Patch `src/engine/application/trading_session.py` — `calendar` + persistência.
3. Patch `src/engine/infrastructure/state/sqlite_store.py` — schema + serialização.
4. Rodar `uv run pytest -q` → ~172 passed.

**Passo 7 — Se algo quebrar:**
- Rodar `uv run pytest -q -x` (para no primeiro erro)
- Comparar com `test_golden_v510.py` se for detector, com `test_regions.py` se
  for região, com `test_presets.py` se for config
- **NÃO** consertar teste quebrando código de produção. Se um teste antigo
  quebrou, é bug de F5e, não do teste.

---

## 9. Bugs conhecidos / pontos de atenção

### Bug cosmético — `breakout` logado 2×
Cada teste que chama `_build_intent()` ou `_mk_sessao_com_regiao()` loga `breakout`
2×. **Não é bug**, é o teste chamando helpers 2×. Cosmético.

### `TradingSession` não injeta `B3Calendar` no `RegionManager`
O `RegionManager` aceita `calendar`, mas o `TradingSession.__init__` **não** passa. Em produção, `_is_within_validity` usa **dias corridos**. **TODO F5e.**

### `session_shift` usa `TradingWindow(start=time(0,0), end=time(0,0))`
Gambiarra para não precisar mudar a assinatura. **TODO F5e:** transformar em `@staticmethod`.

### `FakeGateway` detecta stop por string (`"sl"` ou `"stop"`)
O `FakeGateway.place_order` usa `is_stop = not is_limit and ("sl" in comment or "stop" in comment)`.
Isso é **frágil** — depende do comment. **TODO F5e:** adicionar campo `is_stop` no `OrderRequest`.

### `SessionSnapshot` não persiste parciais/reforço
O `_current_entry_price`, `_current_is_buy`, `_reentry_armed`, `_reentry_done`, `_partials_filled` **não são salvos** no `save_state()`. Se o motor reiniciar no meio de um trade, o reforço é perdido. **TODO F5e.**

### `SimulatedExecutor` não implementa parciais
Só SL/TP final. F5e implementa.

### `SimulatedExecutor` não implementa slippage/spread
Só fill ingênuo. F5e implementa.

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

### Parciais: `place_partial_orders` chama `symbol_info` de novo
- `place_partial_orders` chama `self._gw.symbol_info(symbol)` para normalizar lotes.
- Poderia reusar o `info` de `execute()`, mas para simplicidade chama de novo.
- **Não é bug**, é decisão de design.

### `_infer_tier_from_comment` depende do comment `engine_partial_N`
- O `Poller` classifica como `PartialFilled` se `"partial" in comment.lower()`.
- O `TradingSession._infer_tier_from_comment` extrai o `N` do `partial_N`.
- Se o `Executor` mudar o formato do comment, os dois quebram juntos.

### Reforço: `place_reentry_exits` usa `comment="engine_reentry_sl"` e `is_limit=False`
- O `FakeGateway` detecta stop por `"sl" in comment`.
- O `Poller` classifica como `ReentryExitFilled` por `"reentry_sl"` no comment.
- Se o `Executor` mudar o comment, os dois quebram juntos.

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
    e `engine_reentry_tp`/`engine_reentry_sl` (saídas). O `is_stop` do `FakeGateway`
    depende de `"sl"` no comment.
15. **Calendário B3:** `B3Calendar` tem feriados hardcoded 2026-2027. Se rodar
    em 2028+, adicione à lista.
16. **`session_shift`:** usa `TradingWindow(start=time(0,0), end=time(0,0))` —
    gambiarra. F5e transforma em `@staticmethod`.