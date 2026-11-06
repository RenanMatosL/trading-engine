# ai_front_end.md — Guia de Retomada do Frontend do Trading Engine

> **Propósito deste arquivo:** permitir que uma IA (ou o autor) retome o
> **frontend** do projeto em outro chat/sessão **sem contexto anterior**,
> saiba **exatamente** onde paramos, o que falta, e o que **não pode ser
> quebrado**.
>
> **Leia este arquivo INTEIRO antes de escrever qualquer linha de código de
> frontend.**
>
> **Este arquivo cobre APENAS o frontend.** Para o backend (motor, estratégia,
> executor, etc.), leia o `ai.md`.

---

## 1. Contexto do frontend

**Objetivo:** dar uma interface web **visual e leve** para o motor de trading
Python (backend em `src/engine/`). Sem React, sem Node.js, sem build step.

**Stack escolhida:**
- **FastAPI** (backend web) + **uvicorn** (servidor ASGI)
- **HTMX** (interatividade sem JS, 48 KB) + plugin `json-enc`
- **Pico.css** (CSS semântico, 83 KB)
- **Jinja2** (templates)
- **uPlot** (gráficos, 52 KB)
- **SSE** (real-time, sem WebSocket) — **F7f**

**Bundle total:** ~185 KB. **Sem Node.js, sem build step.**

**Justificativa:** o projeto já tem tudo em Python. Adicionar FastAPI é 1 `pip
install`. HTMX permite UI interativa sem escrever JS. Pico.css dá visual
decente sem CSS custom.

---

## 2. Estado atual (linha do tempo)

| Fase | Descrição | Status |
|---|---|---|
| **F7a** | Setup FastAPI + Pico + HTMX + `/api/status` + dashboard | ✅ **fechado** |
| **F7b-1** | Tabela `trades` no SQLite + `save_trade` em `on_trade_event` | ✅ **fechado** |
| **F7b-2** | Dashboard com equity curve (uPlot) + tabela de trades | ✅ **fechado** |
| **F7c** | Config (edição de preset via formulário) | ✅ **fechado** |
| **F7d** | Backtest (upload CSV + resultado) | ✅ **fechado** |
| **F7e** | Shadow (rodar + resultado) | ✅ **fechado** |
| **F7f** | SSE (status em tempo real) | ⏳ **PRÓXIMO** |
| **F7g** | Testes (TestClient do FastAPI) | ⏳ pendente |
| **F7f-candles** | Gráfico de candles (Lightweight Charts) | ⏳ opcional |

**Suíte de testes do backend + frontend:** **231 passed** (`uv run pytest -q`).

---

## 3. Arquitetura (mapa de arquivos)
src/engine/web/ # Frontend (F7a+)
├── init.py # vazio
├── app.py # FastAPI app + rotas (F7a, F7d, F7e)
├── deps.py # dependências (gateway, settings) (F7a)
├── schemas.py # Pydantic (request/response) (F7a + F7b-2)
├── routes/
│ ├── init.py
│ ├── trades.py # GET /api/trades (F7b-2)
│ ├── equity.py # GET /api/equity (F7b-2)
│ ├── preset.py # GET/POST /api/preset (F7c)
│ ├── backtest.py # GET/POST /api/backtest (F7d)
│ ├── shadow.py # GET/POST /api/shadow (F7e)
│ └── stream.py # GET /stream (SSE) (F7f - pendente)
├── templates/
│ ├── base.html # layout + HTMX + Pico + uPlot + json-enc
│ ├── dashboard.html # página principal (F7a + F7b-2)
│ ├── _status.html # partial (status) (F7a)
│ ├── _trades.html # partial (trades) (F7b-2)
│ ├── _equity.html # partial (equity, uPlot) (F7b-2)
│ ├── config.html # página de config (F7c)
│ ├── _preset.html # partial (formulário, 7 blocos) (F7c)
│ ├── backtest.html # página de backtest (F7d)
│ ├── _backtest.html # partial (backtest, form + resultado) (F7d)
│ ├── shadow.html # página de shadow (F7e)
│ └── _shadow.html # partial (shadow, form + resultado) (F7e)
└── static/
├── htmx.min.js # 48 KB (F7a)
├── pico.min.css # 83 KB (F7a)
├── uplot.min.js # 50 KB (F7b-2)
└── uplot.min.css # 1.9 KB (F7b-2)

tests/
└── test_web.py # 16 testes (F7b-2 + F7c + F7d + F7e)

Arquivos de documentação:
ai_front_end.md # ESTE arquivo

text

**Reuso do backend:** o frontend **NÃO reimplementa** lógica. Ele chama
`engine.application.*` (TradingSession, RealExecutor, Backtester, ShadowComparer, etc).

---

## 4. Decisões de arquitetura (NÃO MUDE SEM MOTIVO FORTE)

### Stack (NÃO MUDE)

| Camada | Tecnologia | Por quê |
|---|---|---|
| Web framework | **FastAPI** | Rápido, async nativo, OpenAPI automático, tipado |
| Servidor | **uvicorn** | Leve, async, production-ready |
| Templates | **Jinja2** | Padrão do FastAPI, auto-escape, rápido |
| Interatividade | **HTMX** + `json-enc` | Sem JS, atributos HTML |
| CSS | **Pico.css** | Semântico, dark mode nativo |
| Gráficos | **uPlot** | Leve (50 KB), rápido |
| Real-time | **SSE** | Nativo do browser, sem WebSocket (F7f) |
| Estado | **SQLite** (já existe) | Reusa o `engine.db` |
| Config | **YAML** (já existe) | Reusa o `presets/*.yaml` |

### Regras de ouro do frontend

1. **Sem Node.js, sem npm, sem build step.**
2. **Sem React, sem Vue, sem Angular.** HTMX resolve 95% dos casos.
3. **Reusar 100% do backend.** Nunca duplicar lógica.
4. **Bundle final < 200 KB.** HTMX (48) + Pico (83) + uPlot (52) = 183 KB. OK.
5. **SSE > WebSocket.** SSE é 1 endpoint, 1 linha de JS (ou 0 com HTMX).
6. **Templates pequenos.** Cada partial faz 1 coisa.
7. **Sem autenticação na primeira versão.** Roda em `localhost`. F8+.
8. **Não expor segredos.** O `.env` (senha MT5) **nunca** vai para o navegador.
9. **Escrita de preset no disco.** `POST /api/preset` sobrescreve o YAML. **Backup `.bak`** é feito antes.
10. **Formulários HTMX** usam `hx-ext="json-enc"` para serializar como JSON aninhado.
11. **Shadow web é READ-ONLY.** O `POST /api/shadow` compara deals já executados. Para rodar em tempo real com ordens, use a CLI (`engine shadow`). O aviso vermelho em `shadow.html` é obrigatório.
12. **Backtest no simulador** (`POST /api/backtest`) NÃO coloca ordens, usa `Backtester` (F6), puro Python.

### Estrutura de URL

| URL | O que mostra | Status |
|---|---|---|
| `/` | Dashboard (status + equity + trades) | ✅ F7a + F7b-2 |
| `/config` | Edição do preset (7 blocos) | ✅ F7c |
| `/backtest` | Upload CSV + resultado | ✅ F7d |
| `/shadow` | Rodar + resultado | ✅ F7e |
| `/api/*` | Endpoints JSON/HTML | ✅ F7a + F7b-2 + F7c + F7d + F7e |
| `/stream` | SSE (status em tempo real) | ⏳ F7f |
| `/static/*` | CSS, JS, imagens | ✅ F7a |

### Endpoints da API

| Método | Rota | O que faz | Fase |
|---|---|---|---|
| `GET` | `/` | Dashboard (HTML) | ✅ F7a |
| `GET` | `/config` | Página de config (HTML) | ✅ F7c |
| `GET` | `/backtest` | Página de backtest (HTML) | ✅ F7d |
| `GET` | `/shadow` | Página de shadow (HTML) | ✅ F7e |
| `GET` | `/api/status` | Conta + detector + regiões (JSON/HTML) | ✅ F7a |
| `GET` | `/api/trades?limit=50` | Últimos trades do SQLite | ✅ F7b-2 |
| `GET` | `/api/equity?limit=1000` | Equity curve | ✅ F7b-2 |
| `GET` | `/api/preset` | Preset YAML → dict (JSON/HTML) | ✅ F7c |
| `POST` | `/api/preset` | Salva preset YAML (valida + backup) | ✅ F7c |
| `GET` | `/api/backtest` | Form de backtest (HTML para HTMX) | ✅ F7d |
| `POST` | `/api/backtest` | Roda backtest (upload CSV) | ✅ F7d |
| `GET` | `/api/shadow` | Form de shadow (HTML para HTMX) | ✅ F7e |
| `POST` | `/api/shadow` | Roda shadow (compara com EA, read-only) | ✅ F7e |
| `GET` | `/stream` | SSE (status em tempo real) | ⏳ F7f |
| `POST` | `/api/run/start` | Inicia `engine run` (background) | F8+ |
| `POST` | `/api/run/stop` | Para `engine run` | F8+ |
| `GET` | `/api/run/status` | Status do `engine run` | F8+ |

---

## 5. Como o HTMX funciona (para a IA que continuar)

**HTMX lê atributos HTML e faz requisições assíncronas.** Sem JS.

**Exemplo: atualizar status a cada 5s**

```html
<div hx-get="/api/status"
     hx-trigger="load, every 5s"
     hx-swap="innerHTML">
  <!-- conteúdo inicial -->
</div>
Exemplo: formulário de config (JSON aninhado)

html
<form hx-post="/api/preset"
      hx-ext="json-enc"
      hx-target="#preset-form"
      hx-swap="outerHTML">
  <input name="detector.length" value="180">
  <input name="detector.std_ref" value="4.0">
  <button type="submit">Salvar</button>
</form>
O hx-ext="json-enc" faz o HTMX serializar o form como JSON aninhado
({"detector": {"length": 180}}) em vez de detector.length=180.

Exemplo: tabela de trades que atualiza a cada 5s

html
<div class="card"
     hx-get="/api/trades?limit=20"
     hx-trigger="load, every 10s"
     hx-swap="innerHTML">
  <h3>Últimos Trades</h3>
</div>
Negociação HTML vs JSON: todos os endpoints da API retornam HTML para
HTMX (header HX-Request: true) e JSON para clientes externos:

python
is_htmx = request.headers.get("hx-request") == "true"
if is_htmx:
    return templates.TemplateResponse(request=request, name="_partial.html", context=...)
return {...}  # JSON
Carregamento tardio (lazy load): no backtest/shadow, a página usa
hx-get + hx-trigger="load" para carregar o form depois do HTML principal:

html
<div id="shadow-form" hx-get="/api/shadow" hx-trigger="load">
  <article class="card"><p>Carregando formulário...</p></article>
</div>
Multipart form (upload de arquivo): para upload de CSV, o <form> precisa
de hx-encoding="multipart/form-data" (senão o HTMX usa urlencoded e o
UploadFile do FastAPI não recebe o arquivo):

html
<form hx-post="/api/backtest"
      hx-encoding="multipart/form-data"
      hx-target="#backtest-form"
      hx-swap="outerHTML">
  <input type="file" name="file" accept=".csv" required>
  ...
</form>
6. Recursos
F7a ✅ — Setup + status (fechado)
O que faz:

src/engine/web/ com app.py, deps.py, schemas.py.

GET / → dashboard (status).

GET /api/status → JSON (API) / HTML (HTMX).

HTMX + Pico.css em static/.

uvicorn engine.web.app:app --reload --port 8000 funciona.

Arquivos:

src/engine/web/__init__.py

src/engine/web/app.py

src/engine/web/deps.py

src/engine/web/schemas.py

src/engine/web/templates/base.html

src/engine/web/templates/dashboard.html

src/engine/web/templates/_status.html

src/engine/web/static/htmx.min.js

src/engine/web/static/pico.min.css

Critério de F7a (atingido):

uvicorn sobe + Application startup complete.

http://localhost:8000 mostra 3 cards (Conta, Símbolo, Detector).

curl http://localhost:8000/api/status retorna JSON.

uv run pytest -q → ~211 passed.

F7b-1 ✅ — Tabela trades no SQLite
O que faz:

Tabela trades no SqliteStateStore (schema + índices).

save_trade(trade), list_trades(limit), list_equity(limit).

TradingSession._save_closed_trade grava o trade quando fecha (SL/TP/close).

Arquivos:

src/engine/domain/state/store.py (+ TradeRecord)

src/engine/infrastructure/state/memory_store.py (+ save_trade)

src/engine/infrastructure/state/sqlite_store.py (+ tabela + 3 métodos)

src/engine/application/trading_session.py (+ _save_closed_trade + chamadas)

Critério (atingido):

uv run pytest tests/test_state.py -v → 19 passed.

uv run pytest -q → 215 passed.

F7b-2 ✅ — Dashboard com equity + trades
O que faz:

GET /api/trades?limit=50 → JSON/HTML (últimos trades do SQLite).

GET /api/equity?limit=1000 → JSON/HTML (equity curve).

Partials _trades.html (tabela) e _equity.html (uPlot chart).

Dashboard atualizado (3 seções: status + equity + trades).

Arquivos:

src/engine/web/routes/trades.py

src/engine/web/routes/equity.py

src/engine/web/templates/_trades.html

src/engine/web/templates/_equity.html

src/engine/web/static/uplot.min.js + .css

src/engine/web/schemas.py (+ TradeSchema + EquityPointSchema)

tests/test_web.py (5 testes)

Critério (atingido):

Dashboard mostra equity curve (uPlot) + tabela de trades.

uv run pytest tests/test_web.py -v → 5 passed.

uv run pytest -q → 220 passed.

Screenshot confirmado: dashboard com 3 cards + equity + trades.

F7c ✅ — Config (edição de preset)
O que faz:

GET /api/preset → JSON/HTML (preset YAML como dict).

POST /api/preset → valida com pydantic + backup .bak + salva YAML.

Página /config com formulário (7 blocos: Identificação, Detector, Sessão,
Entrada, Stop, TP, Risco, Regiões).

Partial _preset.html (formulário com <input> por campo).

Arquivos:

src/engine/web/routes/preset.py

src/engine/web/templates/config.html

src/engine/web/templates/_preset.html

src/engine/web/app.py (+ GET /config + include_router)

src/engine/web/templates/base.html (+ plugin json-enc do HTMX)

tests/test_web.py (+5 testes)

Critério (atingido):

http://localhost:8000/config mostra formulário com 7 blocos.

Editar detector.length de 180 para 200 → salvar → YAML atualizado.

Backup .bak criado.

Valor inválido (length=1) → 400 com erro.

uv run pytest tests/test_web.py -v → 10 passed.

uv run pytest -q → 225 passed.

Screenshot confirmado: formulário completo.

F7d ✅ — Backtest (fechado)
O que faz:

GET /backtest → página com card de upload (HTML).

GET /api/backtest → partial com form (HTMX lazy load).

POST /api/backtest → upload CSV + parâmetros → roda Backtester → partial com resultado ou erro.

Suporta upload multipart (hx-encoding="multipart/form-data").

Arquivos:

src/engine/web/routes/backtest.py

src/engine/web/templates/backtest.html

src/engine/web/templates/_backtest.html

src/engine/web/app.py (+ GET /backtest + include_router)

tests/test_web.py (+3 testes)

Critério (atingido):

Upload de tests/fixtures/sample_bars.csv → card verde com 10 candles, 0 trades.

Upload de CSV inválido → card vermelho com erro 400.

uv run pytest -q → 228 passed.

Screenshot confirmado: card verde "Resultado do Backtest" com Candles=10, Trades=0.

F7e ✅ — Shadow (fechado)
O que faz:

GET /shadow → página com aviso vermelho (read-only, ordens só via CLI).

GET /api/shadow → partial com form (HTMX lazy load).

POST /api/shadow → coleta deals via gateway.history_deals(since, magic=...),
compara com ShadowComparer (F4), retorna ShadowReport (matched, ea_only,
py_only, mismatches, match_rate, divergências).

Arquivos:

src/engine/web/routes/shadow.py (+ _ShadowTrade wrapper)

src/engine/web/templates/shadow.html

src/engine/web/templates/_shadow.html

src/engine/web/app.py (+ GET /shadow + include_router + limpeza de
test_* mortos no final)

tests/test_web.py (+3 testes)

Critério (atingido):

http://localhost:8000/shadow mostra aviso vermelho + form.

ea_magic inválido (0) → 400 com erro.

ea_magic válido → card verde com Match Rate 100% (sem deals).

uv run pytest -q → 231 passed.

Screenshot confirmado: página shadow com aviso + form completos.

F7f ⏳ — SSE (2h) - PRÓXIMO
O que faz:

GET /stream → SSE que envia status a cada 2s.

Dashboard consome via hx-ext="sse" + sse-connect.

Critério:

Dashboard atualiza sozinho a cada 2s (sem refresh manual).

F7g ⏳ — Testes (3h)
O faz: ~10 testes já existem em test_web.py (F7b-2 + F7c + F7d + F7e). Adicionar mais se necessário.

Critério:

uv run pytest -q → ~240 passed.

7. Como o próximo agente deve começar (F7f)
Passo 1 — Confirmar estado do backend:

powershell
uv run pytest -q
Deve mostrar 231 passed. Se não, PARE e investigue.

Passo 2 — Ler este ai_front_end.md inteiro. Principalmente seções 4
(decisões), 6 (recursos) e a seção 8 (bugs conhecidos).

Passo 3 — Confirmar que o uvicorn sobe:

powershell
uv run uvicorn engine.web.app:app --reload --port 8000
Abra http://localhost:8000. Deve mostrar dashboard com 3 cards + equity + trades.
Abra http://localhost:8000/config. Deve mostrar o formulário.
Abra http://localhost:8000/backtest. Deve mostrar o card de upload.
Abra http://localhost:8000/shadow. Deve mostrar o aviso vermelho + form.

Passo 4 — Começar F7f:

Criar src/engine/web/routes/stream.py (endpoint GET /stream SSE).

Adicionar include_router no app.py.

Adicionar <div hx-ext="sse" sse-connect="/stream" sse-swap="message"> no dashboard.html.

Adicionar testes em test_web.py.

Rodar uv run pytest -q → ~235 passed.

Passo 5 — Se algo quebrar:

uv run pytest -q → se quebrar, é bug do F7f, não do backend.

Navegador → se 404/500, confira os logs do uvicorn.

SSE → se não atualizar, verifique se o endpoint tem media_type="text/event-stream".

8. Bugs conhecidos / pontos de atenção
✅ RESOLVIDO (F7a) — TemplateResponse com assinatura antiga
Sintoma: TypeError: unhashable type: 'dict'.
Causa: Starlette ≥ 0.30 mudou a assinatura.
Fix: TemplateResponse(request=request, name="...", context={...}) (kwargs explícitos).

✅ RESOLVIDO (F7a) — IPC initialize failed no MT5
Sintoma: mt5.initialize() retorna False + (-10003, 'IPC initialize failed').
Causa: "Python Integration" desabilitado no MT5.
Fix: MT5 → Ferramentas → Opções → Comunidade → "Integração com Python" → Reiniciar MT5.

✅ RESOLVIDO (F7b-2) — httpx faltando
Sintoma: RuntimeError: The starlette.testclient module requires the httpx2 package.
Fix: uv pip install httpx + adicionar ao extra dev do pyproject.toml.

✅ RESOLVIDO (F7c) — lifespan sobrescrevia preset_path
Sintoma: o teste test_api_preset_get_json retornava "v510_default" em vez de "test".
Causa: o lifespan sobrescrevia app.state.preset_path com settings.preset.
Fix: if not hasattr(app.state, "preset_path"): app.state.preset_path = settings.preset (só seta se não existir).

✅ RESOLVIDO (F7c) — _get_preset_path usava settings.preset
Sintoma: o POST /api/preset salvava no YAML real (não no temporário do teste).
Fix: _get_preset_path usa app.state.preset_path (se existir) ou fallback settings.preset.

✅ RESOLVIDO (F7c) — formulário HTMX precisa de hx-ext="json-enc"
Sintoma: o POST /api/preset recebia detector.length=180 (form-urlencoded) em vez de JSON aninhado.
Fix: <form hx-post="..." hx-ext="json-enc"> + plugin json-enc.js no base.html.

✅ RESOLVIDO (F7d) — TemplateNotFound: 'backtest.html'
Sintoma: GET /backtest → 500 jinja2.exceptions.TemplateNotFound: 'backtest.html' not found.
Causa: o padrão do projeto é _partial.html para partials e page.html para páginas completas. O app.py pedia "backtest.html" mas só existia "_backtest.html" (partial).
Fix: criar backtest.html (página, {% extends "base.html" %}, {% block content %}, {% include "_backtest.html" %}).

✅ RESOLVIDO (F7d) — TemplateResponse sem request=request
Sintoma: TypeError: TemplateResponse.__init__() missing 1 required positional argument: 'request'.
Causa: o routes/backtest.py chamava _error(..., request, is_htmx) mas a função _error tinha assinatura antiga (_error(msg, is_htmx)).
Fix: padronizar _error(msg, request, is_htmx) em todos os routers novos.

✅ RESOLVIDO (F7d) — código de teste dentro do app.py
Sintoma: o app.py tinha 3 funções test_* no final (código morto, não rodava no pytest).
Fix: remover e mover para tests/test_web.py (com fixtures client e preset_file).

✅ RESOLVIDO (F7e) — TradeIntent obrigatório no routes/shadow.py
Sintoma: TypeError: TradeIntent.__init__() missing ... region, volume, reason, created_at.
Causa: o ShadowComparer só precisa de bar_time, is_buy e entry_price, mas o meu primeiro rascunho do router tentou construir um TradeIntent inteiro.
Fix: criar @dataclass _ShadowTrade no próprio routes/shadow.py (duck typing) com só os 3 campos usados.

⚠️ ATENÇÃO — test_web.py precisa de import yaml
Se você criar novos testes que usam yaml.safe_dump ou yaml.safe_load, adicione import yaml no topo.

FastAPI + Jinja2: request é obrigatório
Toda chamada a TemplateResponse precisa de request=request:

python
return templates.TemplateResponse(request=request, name="dashboard.html", context={...})
HTMX: hx-trigger="every 5s" não para sozinho
Se a aba ficar aberta por horas, o HTMX continua chamando /api/status a cada 5s. Não é bug.

SSE: StreamingResponse precisa de media_type="text/event-stream"
Sem media_type, o browser não reconhece como SSE.

Pico.css: usa data-theme="dark" no <html>
Para dark mode:

html
<html data-theme="dark">
uPlot: precisa de uplot.min.css
Sem o CSS, o gráfico fica sem estilo.

engine.db no navegador? NÃO
O SQLite fica no servidor. O navegador só vê JSON.

.env no navegador? NÃO
O .env tem a senha do MT5. Nunca exponha.

HTMX: hx-swap="outerHTML" substitui o próprio elemento
Sempre inclua os atributos hx-* na resposta HTML (ou use hx-swap="innerHTML").

FastAPI: Depends para injetar gateway
Use Depends(get_gateway) para injetar o BrokerGateway nas rotas.

Pydantic v2: model_dump(mode="json") para serializar
model_dump() puro retorna datetime (não serializável por JSON).

TestClient: with TestClient(app) as client: para rodar lifespan
O TestClient não dispara o lifespan (startup/shutdown) se você não usar with.

pyproject.toml: adicionar web e httpx como extra
toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.4", "mypy>=1.10", "httpx>=0.27"]
web = ["fastapi>=0.110", "uvicorn[standard]>=0.29", "jinja2>=3.1", "python-multipart>=0.0.9"]
uvicorn precisa de uv run
O comando uvicorn não funciona sem uv run:

powershell
uv run uvicorn engine.web.app:app --reload --port 8000
Symbol — WIN$N vs WINZ26
O .env tem ENGINE_MT5__SYMBOL=WIN$N, mas a Clear usa WINZ26. O MT5 resolve WIN$N para WINZ26 automaticamente.

_backtest.html e _shadow.html — partials HTMX
Ambos começam com {# ... #} (comentário Jinja) e são retornados por TemplateResponse em GET e POST. O POST com hx-swap="outerHTML" substitui o <div id="backtest-form"> (ou #shadow-form) pelo partial inteiro — o form aparece de novo junto com o resultado. Isso é intencional (permite rodar de novo sem refresh).

9. Comandos úteis
powershell
# Setup
uv pip install -e ".[mt5,dev,web]"

# Rodar (dev)
uv run uvicorn engine.web.app:app --reload --port 8000

# Rodar (prod)
uv run uvicorn engine.web.app:app --host 0.0.0.0 --port 8000 --workers 1

# Testar backend + frontend
uv run pytest -q

# Curl (API)
curl http://localhost:8000/api/status
curl http://localhost:8000/api/trades?limit=10
curl http://localhost:8000/api/equity?limit=100
curl http://localhost:8000/api/preset
curl -X POST http://localhost:8000/api/preset -H "Content-Type: application/json" -d '{"name":"test","strategy":"stddev_v510"}'

# Curl (HTML)
curl http://localhost:8000/
curl http://localhost:8000/config
curl http://localhost:8000/backtest
curl http://localhost:8000/shadow

# Verificar templates
dir src\engine\web\templates\
dir src\engine\web\static\
10. Referências externas
FastAPI: https://fastapi.tiangolo.com

uvicorn: https://www.uvicorn.org

HTMX: https://htmx.org

Pico.css: https://picocss.com

uPlot: https://github.com/leeoniya/uPlot

Jinja2: https://jinja.palletsprojects.com

SSE (MDN): https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events

Backend: leia o ai.md (motor, estratégia, executor, etc).

11. Regras de ouro (para a IA que continuar)
Rode uv run pytest -q antes e depois de CADA mudança no frontend.
O backend tem que continuar 231 passed.

Nunca duplique lógica do backend. Sempre importe de engine.application.*
e engine.infrastructure.*.

Não exponha engine.db nem .env. O navegador só vê JSON público.

Prefira hx-swap="innerHTML" com partials que têm os atributos hx-*.

Templates pequenos. Cada _partial.html faz 1 coisa.

Pydantic v2 para schemas de request/response. model_dump(mode="json")
para serializar.

TestClient do FastAPI com with TestClient(app) as client: para disparar
o lifespan.

Não use CDN em produção. Baixe HTMX/Pico/uPlot para static/.
Para dev, CDN é OK.

Se um teste do backend quebrar, é bug do frontend (provavelmente você
mudou um import ou duplicou código). PARE e investigue antes de continuar.

Quando em dúvida, pergunte. O autor tem contexto do backend e sabe
quando uma mudança quebra paridade.

MT5 precisa estar aberto + logado antes de uvicorn. Se o IPC falhar,
verifique "Python Integration" no MT5.

Sempre uv run antes de uvicorn/pytest/engine/python.

TemplateResponse(request=request, name="...", context={...}) — assinatura
do Starlette ≥ 0.30. Não use TemplateResponse("name", {...}).

Formulários HTMX usam hx-ext="json-enc" para serializar como JSON
aninhado ({"detector": {"length": 180}}). Uploads usam
hx-encoding="multipart/form-data".

Backup de preset: o POST /api/preset copia o YAML atual para .bak
antes de salvar.

Padrão de template: partials começam com _ (_status.html,
_backtest.html, _shadow.html); páginas não (dashboard.html,
backtest.html, shadow.html). O app.py pede pela página; o router
pede pelo partial.

_error(msg, request, is_htmx) — assinatura padrão em todos os
routers novos (F7d+). O request é obrigatório para TemplateResponse.

Código de teste NUNCA no app.py. Sempre em tests/test_web.py.