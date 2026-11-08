# MANUAL.md — Manual de Operação do Trading Engine

> **Propósito:** guia passo a passo, em ordem **cronológica**, de como operar o
> motor em cada fase (dev → demo → real), como comparar com o EA, como ver
> ganhos/perdas/métricas, e o que cada recurso faz.
>
> **Leia o `README.md` primeiro** (visão geral) e o `AI.md` se for retomar o projeto.
> Este manual é para **usar** o motor, não para modificá-lo.

---

## Índice

1. [Pré-requisitos](#1-pré-requisitos)
2. [Instalação (5 min)](#2-instalação-5-min)
3. [Configuração inicial (.env)](#3-configuração-inicial-env)
4. [Sanidade — "tá tudo funcionando?"](#4-sanidade--tá-tudo-funcionando)
5. [Frontend web](#5-frontend-web)
6. [Fase 1 — Desenvolvimento (sem MT5)](#6-fase-1--desenvolvimento-sem-mt5)
7. [Fase 2 — Conexão ao MT5 (leitura)](#7-fase-2--conexão-ao-mt5-leitura)
8. [Fase 3 — Loop real em demo](#8-fase-3--loop-real-em-demo)
9. [Fase 4 — Modo sombra (comparar com o EA)](#9-fase-4--modo-sombra-comparar-com-o-ea)
10. [Fase 5 — Backtest (sem MT5)](#10-fase-5--backtest-sem-mt5)
11. [Operação em Conta Demo e Real](#11-operação-em-conta-demo-e-real)
12. [Calibração (usando o gráfico)](#12-calibração-usando-o-gráfico)
13. [Recursos detalhados](#13-recursos-detalhados)
14. [Como ver ganhos, perdas e métricas](#14-como-ver-ganhos-perdas-e-métricas)
15. [Troubleshooting](#15-troubleshooting)
16. [Glossário](#16-glossário)

---

## 1. Pré-requisitos

| Item | Requisito |
|---|---|
| **Sistema** | Windows (para MT5 real); Linux/Mac só para `--fake`, `--backtest` e **frontend** |
| **Python** | 3.11+ |
| **UV** | Gerenciador de pacotes ([instalação](https://docs.astral.sh/uv/)) |
| **MT5** | Instalado e aberto (para `engine run --demo` / `--real` / `shadow`) |
| **Conta MT5** | Demo ou real, com login/senha/servidor |
| **Dados** | Histórico de candles M1 do `WIN$N` carregado no MT5 (mín. 200 candles) |
| **Navegador** | Chrome, Firefox, Edge (para o frontend) |

---

## 2. Instalação (5 min)

### 2.1 — Clonar o repositório

```powershell
git clone https://github.com/RenomadDev/trading-engine.git
cd trading-engine
2.2 — Instalar uv (uma vez)
powershell
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux/Mac
curl -LsSf https://astral.sh/uv/install.sh | sh
2.3 — Criar venv e instalar dependências
powershell
uv venv
uv pip install -e ".[mt5,dev,web]"
Nota: em Linux/Mac (sem MT5), use só [dev,web]:

bash
uv pip install -e ".[dev,web]"
2.4 — Verificar instalação
powershell
uv run engine version      # deve imprimir "0.1.0"
uv run pytest -q           # deve imprimir "241 passed"
Se der 241 passed, a instalação está OK.

3. Configuração inicial (.env)
3.1 — Criar .env a partir do exemplo
powershell
copy .env.example .env
3.2 — Preencher .env
Abra .env no editor e preencha:

env
# Conta MT5 (demo ou real)
ENGINE_MT5__LOGIN=2194515615
ENGINE_MT5__PASSWORD=sua_senha
ENGINE_MT5__SERVER=ClearInvestimentos-DEMO
ENGINE_MT5__SYMBOL=WINZ26

# Caminho do terminal MT5 (opcional, se instalado no padrão)
ENGINE_MT5__TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe

# Preset default (caminho relativo)
ENGINE_PRESET=presets/stddev_v510_default.yaml

# Log em JSON (false = legível)
ENGINE_LOG_JSON=false
3.3 — Segurança
⚠️ NUNCA commite o .env (ele está no .gitignore). Se vazar, troque a senha imediatamente.

3.4 — Verificar que o preset carrega
powershell
uv run engine check-config
Esperado:

text
preset_valido  nome=v510_default  estrategia=stddev_v510
               detector={length: 180, std_ref: 4.0, ...}
               session={window: {...}, ...}
               ...
Se der 7 seções no log, o preset está OK.

4. Sanidade — "tá tudo funcionando?"
4.1 — Testes unitários
powershell
uv run pytest -q
Esperado: 241 passed.

4.2 — CLI funciona?
powershell
uv run engine version
uv run engine check-config
4.3 — Detector funciona com dados sintéticos?
powershell
uv run engine status --fake
Esperado:

text
engine_status  conta=0 servidor=FAKE saldo='100,000.00 BRL'
               simbolo=WIN$N candles=180
detector       z=11.27 media=2145.8 desvio=1140.8 candle_sinal=True
Se o detector aparecer com z=11.27 e candle_sinal=True, o detector está OK.

4.4 — Loop funciona sem MT5?
powershell
uv run engine run --dry-run --fast --max-ticks 10
Esperado:

text
strategy_registered        magic=0 name=stddev_v510
strategy_session_created   magic=0 name=stddev_v510 preset=v510_default
engine_run_start           n_strategies=1 strategies=['stddev_v510']
engine_run_max_ticks       ticks=11
5. Frontend web
O que é: dashboard web (FastAPI + HTMX + Pico.css + uPlot) para acompanhar o motor em tempo real (via SSE), editar o preset, ver trades/equity, rodar backtests e comparar com o EA (shadow).

5.1 — Iniciar o servidor web
powershell
uv run uvicorn engine.web.app:app --reload --port 8000
Pré-requisito: MT5 aberto e logado (demo) antes de rodar o uvicorn. O startup_gateway conecta no MT5.

Esperado:

text
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [XXXX]
INFO:     Started server process [XXXX]
INFO:     Waiting for application startup.
2026-11-06 XX:XX:XX [info] web_gateway_real login=2194515615
INFO:     Application startup complete.
Abra http://localhost:8000 → dashboard.

📄 Seção 5.2 — Telas do frontend
markdown
### 5.2 — Telas do frontend

| URL | O que mostra |
|---|---|
| `/` | **Dashboard** (status em tempo real via SSE + equity curve + tabela de trades) |
| `/config` | **Edição do preset** (formulário com 7 blocos) |
| `/backtest` | **Backtest** (upload CSV + resultado numérico + gráfico de candles com volume e ferramentas) |
| `/shadow` | **Shadow** (comparar com EA — read-only) |
| `/metrics` | **Métricas Prometheus** (formato `text/plain`, para monitoramento externo via Grafana/Prometheus) |


5.3 — Dashboard (/)
3 cards no topo (atualizam a cada 2s via SSE):

Conta: login, servidor, saldo.

Símbolo: barras carregadas, último candle, fechamento.

Detector: z-score, média, desvio, volume, sinal.

Equity Curve (uPlot):

Curva do saldo acumulado ao longo dos trades.

Atualiza a cada 10s.

Últimos Trades (tabela):

Exit time, direção (BUY/SELL), entry, exit, P&L, motivo (take_profit/stop_loss/end_of_day).

Atualiza a cada 10s.

Nota: para ver trades, o engine.db precisa estar populado (rode engine run --dry-run --fast --max-ticks 100 ou insira trades manualmente via seed_trades.py).

5.4 — Config (/config)
Formulário com 7 blocos:

Identificação: nome, estratégia.

Detector: length, std_ref, volume_source, timeframe, mute_open_min.

Sessão: início, fim, close_outside, carry_delay, breakout_ttl, cooldown, max_trades_day, entry_block.

Entrada: modo, offset, as_pending, max_entry_gap_points.

Stop Loss: modo, sl_points, level_offset_points.

Take Profit: use_final_tp, final_tp_points.

Risco: sizing_mode, total_contracts, lot_per_contract, risk_mode, risk_value, use_partial_exit, use_reentry.

Regiões: max_loc, valid_days, candidate_mode.

Modo do Gatilho: trigger_mode, trap_arm_points, trap_style, trap_sl_points.

Ações:

Salvar preset: valida com pydantic, faz backup .bak, salva YAML.

Recarregar (descarta): descarta edições, recarrega do YAML.

Segurança: o backup .bak é criado em presets/stddev_v510_default.yaml.bak antes de sobrescrever.

5.5 — Backtest (/backtest)
O que faz: roda o motor sobre um CSV de candles (sem MT5). Agora com parciais e reforço (F8), refletindo com precisão o comportamento real. F10: visualização gráfica com candles, volume, timeframes e ferramenta de medição.

Passo a passo:

Clique em "Escolher arquivo" e selecione um CSV (ex: tests/fixtures/sample_bars.csv).

Ajuste o saldo inicial (default: 100.000).

Clique em "Rodar backtest".

O card verde com as métricas (Candles, Trades, Win Rate, PnL, Return, Sharpe, Max Drawdown, Profit Factor, Avg Win / Loss) aparece no topo.

O gráfico de candles é renderizado abaixo, com:

Setas verdes (compras) e vermelhas (vendas).

Círculos (saídas) nos candles onde os trades foram fechados.

Volume (histograma) abaixo dos candles.

Seletor de timeframe (1M, 5M, 15M, 30M, 4H, D, M).

Shift + arrastar para medir a distância em pontos entre dois níveis de preço.

Duplo clique para limpar a medição.

Nota 1: o CSV precisa ter no mínimo 180 candles para o detector gerar trades. O fixture sample_bars.csv tem 10 candles, então o resultado será Trades=0 (comportamento esperado).

Nota 2: O CSV exportado do MT5 (com tabulação/UTF-16) é aceito automaticamente pelo csv_loader.py (F8+).

5.6 — Shadow (/shadow)
O que faz: compara os deals já executados pelo EA (MQL5) com os deals do Python em uma janela de tempo. Read-only (não coloca ordens).

Aviso vermelho na tela: "Esta página apenas compara deals já executados no MT5. Para rodar em tempo real com ordens reais, use a CLI".

Passo a passo:

Preencha o EA Magic (obrigatório, ex: 20260718).

(Opcional) Preencha o Python Magic (default: EA + 1).

(Opcional) Ajuste a Duração (em minutos, default: 60).

(Opcional) Ajuste a Tolerância (em pontos, default: 2.0).

Clique em "Comparar".

Resultado esperado: card verde com Match Rate, matched, mismatches, EA Only, Python Only, Total EA / Py, e uma tabela de divergências (se houver).

6. Fase 1 — Desenvolvimento (sem MT5)
Objetivo: validar a lógica sem tocar em MT5.

6.1 — Rodar o loop com FakeGateway
powershell
uv run engine run --dry-run --fast --max-ticks 100
O FakeGateway gera preços sintéticos (171000 ± 50). O TradingSession roda igual à produção, mas sem tocar em MT5.

6.2 — O que observar no log
Log	Significado
strategy_registered	Estratégia registrada no StrategyRegistry
strategy_session_created	Sessão criada (1 por estratégia)
engine_run_start	Loop iniciado
breakout	Região rompeu (direção definida)
executor_place_order	Ordem colocada
executor_place_partial	Parcial armada
end_of_day_closed	Fim do dia — posições fechadas
engine_run_max_ticks	Loop encerrado (limite atingido)
6.3 — Persistência funciona?
powershell
dir engine.db
Esperado: engine.db criado (SQLite). O estado (regiões, trades_today, cooldown) persiste entre execuções.

Nota: para não poluir o projeto, use --db :memory::

powershell
uv run engine run --dry-run --fast --max-ticks 10 --db :memory:
7. Fase 2 — Conexão ao MT5 (leitura)
Objetivo: validar que o motor consegue ler conta, barras e preço do MT5 real.

7.1 — Pré-requisitos
MT5 aberto e logado (demo).

.env configurado (login/senha/servidor).

Símbolo WINZ26 carregado no Market Watch do MT5.

7.2 — Verificar conexão
powershell
uv run engine status
Esperado:

text
engine_status  conta=2194515615 servidor=ClearInvestimentos-DEMO
               saldo='989,716.00 BRL' simbolo=WINZ26 candles=180
detector       z=X.XX media=... desvio=... candle_sinal=False
Se der mt5_indisponivel, o MT5 não está aberto ou o .env está errado.

7.3 — O que observar
conta deve ser seu login demo.

candles=180 (ou mais).

detector deve mostrar z calculado sobre os últimos 180 candles.

8. Fase 3 — Loop real em demo
Objetivo: rodar o motor em tempo real contra a conta demo, colocando ordens de verdade (mas em demo).

8.1 — Configurar conta demo no .env
env
ENGINE_MT5__LOGIN=2194515615
ENGINE_MT5__PASSWORD=<sua senha demo>
ENGINE_MT5__SERVER=ClearInvestimentos-DEMO
ENGINE_MT5__SYMBOL=WINZ26
8.2 — Rodar o loop
powershell
uv run engine run --demo --db engine_demo.db --poll-interval 2
Flags:

--demo: usa RealMT5Gateway (conexão real).

--db engine_demo.db: SQLite separado.

--poll-interval 2: 1 iteração a cada 2 segundos.

8.3 — O que observar
No log:

text
engine_run_start   symbol=WINZ26 dry_run=False n_strategies=1
breakout           bar_time=... is_buy=True stop=800.0 tp=1700.0
executor_place_order  is_buy=True volume=6 price=1100 retcode=10009 ok=True
No MT5 (aba "Trade"):

Ordens pendentes (BuyLimit/SellLimit).

Quando o preço atinge o nível, a ordem é preenchida.

Parciais aparecem como ordens pendentes separadas.

No engine_demo.db:

regions (SQLite) tem as regiões ativas.

session_state tem o estado (cooldown, trades_today).

trades (F7b-1) tem os trades fechados.

8.4 — Parar o loop
Pressione Ctrl+C. O motor salva o estado e fecha o SQLite.

8.5 — Retomar depois
Basta rodar o mesmo comando. O motor carrega o estado do SQLite (_load_state) e continua de onde parou (regiões, cooldown, trades_today, parciais, reforço).

9. Fase 4 — Modo sombra (comparar com o EA)
Objetivo: rodar o motor Python em paralelo ao EA v4.60 (no mesmo MT5) e comparar as decisões.

9.1 — Pré-requisitos
MT5 aberto (demo).

EA StdDevVolumeBreakout.mq5 rodando no gráfico do WINZ26 M1.

EA com magic 20260718 (default do EA v4.60).

9.2 — Rodar o shadow
powershell
uv run engine shadow --ea-magic 20260718 --duration 30 --poll-interval 2
9.3 — O que acontece
O motor Python também opera (coloca ordens com magic 0, distinto do EA).

Ao fim de 30 min, compara history_deals dos dois magics.

Gera relatório em reports/shadow_YYYYMMDD_HHMMSS.json.

9.4 — Analisar o relatório
powershell
type reports\shadow_*.json
Estrutura:

json
{
  "start": "2026-11-06T10:00:00+00:00",
  "end": "2026-11-06T10:30:00+00:00",
  "matched": 3,
  "ea_only": 0,
  "py_only": 0,
  "mismatches": 0,
  "total_ea": 3,
  "total_py": 3,
  "match_rate": 1.0,
  "divergences": []
}
9.5 — Interpretar
Campo	Significado	Meta
match_rate	matched / max(total_ea, total_py)	> 0.95 (ideal 1.0)
matched	Trades iguais	Alto
ea_only	Trades que EA fez e Python não	Baixo
py_only	Trades que Python fez e EA não	Baixo
mismatches	Ambos fizeram, mas com preço/direção diferentes	Baixo
10. Fase 5 — Backtest (sem MT5)
Objetivo: rodar backtest sobre um CSV de candles, sem MT5.

10.1 — Preparar o CSV
Opção A: Formato padrão do projeto:

csv
time,open,high,low,close,tick_volume,real_volume
2026-10-29 09:00:00,170900,171020,170850,170950,2500,0
2026-10-29 09:01:00,170950,171100,170900,171050,3200,0
...
Opção B: Formato exportado pelo MT5 (tabulação, UTF-16):
O csv_loader.py (F8+) aceita automaticamente o CSV do MT5, que tem este formato:

text
<DATE>	<TIME>	<OPEN>	<HIGH>	<LOW>	<CLOSE>	<TICKVOL>	<VOL>	<SPREAD>
2026.05.12 17:12	193590	193590	193590	193590	1	1	0
10.2 — Rodar o backtest
powershell
uv run engine backtest --csv meu_historico.csv
Flags:

--csv: caminho do CSV (obrigatório).

--preset: preset (default: o do .env).

--from-date 2026-01-01: filtra candles a partir de.

--to-date 2026-12-31: filtra candles até.

--initial-balance 100000: saldo inicial.

--slippage 2: slippage em pontos.

--spread 1: spread em pontos (reservado).

--output result.json: salva resultado em JSON.

10.3 — O que observar
text
backtest_result  preset=v510_default n_bars=10000 start=2026-01-01T09:00:00
                 end=2026-12-30T17:30:00 n_trades=42 winners=25 losers=17
                 win_rate=0.5952 total_pnl=12345.67 return_pct=12.35
                 sharpe=1.23 max_drawdown_pct=4.56 profit_factor=1.89
Campo	Significado
n_bars	Candles processados
n_trades	Trades fechados
winners / losers	Trades com lucro / prejuízo
win_rate	winners / n_trades (0.0 a 1.0)
total_pnl	Lucro total em R$
return_pct	Retorno % sobre o saldo inicial
sharpe	Sharpe ratio anualizado
max_drawdown_pct	Pior queda % do equity
profit_factor	Lucro bruto / |prejuízo bruto|
Nota F8: o simulador agora respeita as parciais (Tier 1/2/3) e o reforço, então o PnL e as métricas refletem o comportamento real do MT5.

10.4 — Modos de entrada (para calibrar)
O comportamento do backtest depende do entry.level_mode no YAML:

Modo	O que faz
default	Entrada no meio da região (ou no extremo - offset, em candle grande).
broken_extreme	Entrada no extremo rompido (pullback raso).
mid	Entrada no meio da região.
opposite_extreme	Entrada no extremo oposto (pullback profundo).
immediate	Entrada a mercado no instante do rompimento.
Nota: Com o modo broken_extreme, o backtest tem gerado resultados muito melhores (ex: +122% de retorno em 9 meses, com 198 trades). O modo trap também está funcional.

11. Operação em Conta Demo e Real
Objetivo: rodar o motor na próxima segunda-feira usando os parâmetros validados no backtest, monitorando em tempo real.

11.1 — Preparação (Véspera / Fim de semana)
Abra o MT5 e faça login na conta (demo ou real).

Confirme que o símbolo está no Market Watch (ex: WINZ26).

Edite o YAML (presets/stddev_v510_default.yaml) com os parâmetros que você validou no backtest (ex: entry.level_mode: broken_extreme, risk.total_contracts: 10, etc).

Teste a conexão:

powershell
uv run engine status
Deve mostrar a conta, saldo e candles.

Rode o backtest novamente com o CSV do último pregão para confirmar que o motor está calibrado (opcional, mas recomendado).

11.2 — Início da Operação (Segunda-feira, antes do pregão)
Abra o MT5 e deixe logado na conta (demo ou real).

Inicie o frontend (para monitorar):

powershell
uv run uvicorn engine.web.app:app --reload --port 8000
Abra outra janela do CMD e inicie o motor em tempo real:

Para conta demo:

powershell
uv run engine run --demo --db engine_demo.db --poll-interval 2
Para conta real:

powershell
uv run engine run --db engine_real.db --poll-interval 1
Verifique o log:

engine_run_start deve aparecer.

O motor vai começar a monitorar o mercado.

Abra o dashboard em http://localhost:8000 para acompanhar.

11.3 — Acompanhamento e Parada
No MT5 (aba "Trade"): veja as ordens sendo abertas (pendentes e a mercado).

No frontend: acompanhe o equity curve e a tabela de trades.

Para parar: pressione Ctrl+C no terminal do motor. Ele salva o estado e fecha o SQLite.

Não feche o MT5 abruptamente.

11.4 — Checklist de Operação (Segunda-feira)
□ .env com credenciais da conta (demo ou real).
□ YAML com os parâmetros validados no backtest.
□ MT5 aberto e logado.
□ Frontend rodando (uvicorn).
□ Motor rodando (engine run).
□ Dashboard acessível em http://localhost:8000.
□ Saldo compatível com o risco (não arrisque > 1% por trade).
□ Windows não vai dormir/desligar.
□ Internet estável.
11.5 — Aviso Importante: Modo Trap
Se você estiver usando o modo trap (trigger_mode: trap), saiba que:

O motor vai inverter as operações (vender quando o preço sobe, comprar quando desce).

No backtest, o modo trap gerou -82% de retorno em 9 meses (perdas consistentes).

Não use o modo trap em conta real sem antes validar em demo por pelo menos 1 mês.

12. Calibração (usando o gráfico)
O que fazer com o resultado do backtest?

Abra o gráfico em /backtest (após rodar o backtest).

Observe os markers:

Setas verdes (compras) e vermelhas (vendas).

Círculos (saídas: TP, SL, fim do dia).

Use a ferramenta de medição (Shift + arrastar) para ver a distância em pontos:

Se os stops estão muito distantes, reduza o sl_points (ex: de 200 para 100).

Se os TPs estão muito próximos, aumente o final_tp_points (ex: de 600 para 1200).

Ajuste o entry.level_mode:

broken_extreme: entrada no rompimento (pullback raso). Melhor para tendências.

default: entrada no meio da região. Melhor para reversões.

Teste novamente com o mesmo CSV e compare os resultados.

Dica: Use o seletor de timeframe (1M, 5M, 15M, etc) para ver o padrão em diferentes escalas.

13. Recursos detalhados
13.1 — engine status
Lê a conta, símbolo, últimos 180 candles, e calcula o z-score do último candle. Não coloca ordens.

13.2 — engine check-config
Valida o preset YAML (pydantic). Não conecta em MT5.

13.3 — engine run
Loop real (dry-run, demo ou real). Flags: --dry-run, --demo, --db, --poll-interval, --max-ticks, --fast, --strategies.

13.4 — engine shadow
Modo sombra (compara com o EA). Flags: --ea-magic, --py-magic, --duration, --poll-interval, --tolerance-points, --report-dir, --db.

13.5 — engine backtest
Backtest sobre CSV. Flags: --csv, --preset, --from-date, --to-date, --initial-balance, --slippage, --spread, --output.

13.6 — Frontend (uvicorn)
Dashboard + config + backtest + shadow. Flags: --reload, --port.

13.7 — Parciais (tiers 1/2/3)
O que faz: divide a saída da posição em 3 partes (tiers). Cada tier vende partial_contracts quando o preço atinge partial_points a favor.

Configuração no YAML:

yaml
risk:
  use_partial_exit: true
  partial_points: 200
  partial_contracts: 2
  partial_as_pending: true
  partial2_points: 400
  partial2_contracts: 2
  partial3_points: 600
  partial3_contracts: 1
  breakeven_after_partial: true
13.8 — Reforço
O que faz: após a entrada, se o preço avança reentry_arm_points a favor e volta ao preço de entrada, o motor reforça a posição.

Configuração no YAML:

yaml
risk:
  use_reentry: true
  reentry_contracts: 3
  reentry_arm_points: 200
  reentry_tp_points: 200
  reentry_sl_points: 200
13.9 — By-risk sizing
O que faz: em vez de contratos fixos, calcula o lote pelo risco.

Configuração no YAML:

yaml
risk:
  sizing_mode: by_risk
  risk_mode: percent_balance
  risk_value: 1.0
13.10 — Calendário B3
O que faz: validade de regiões por pregões reais (dias úteis, sem feriados), não dias corridos.

Feriados hardcoded 2026-2027 (em exchange_calendar.py). Atualizar 2028+.

13.11 — Multi-estratégia
O que faz: roda N estratégias no mesmo motor, cada uma com seu magic.

powershell
uv run engine run --dry-run --fast --max-ticks 3 --strategies=stddev_v510
14. Como ver ganhos, perdas e métricas
14.1 — No frontend (http://localhost:8000)
Card de status: conta, símbolo, detector.

Equity Curve (uPlot): curva do saldo acumulado.

Últimos Trades (tabela): Exit time, direção, entry, exit, P&L, motivo.

Backtest (/backtest): upload de CSV, métricas completas e retorno.

Shadow (/shadow): Match Rate, divergências, total EA/Py.

14.2 — No log do engine run
Log estruturado (structlog) mostra cada ordem e cada evento:

text
executor_place_order  is_buy=True volume=6 price=1100 retcode=10009 ok=True
trade_event_entry     position=12345 volume=6 price=1100
trade_event_tp_consume region=...
14.3 — No MT5 (aba "Trade")
"Posições": posições abertas.

"Histórico": trades fechados.

"Ordens": ordens pendentes.

14.4 — No SQLite (engine.db)
Use DB Browser for SQLite para abrir engine.db:

Tabela regions: regiões ativas, consumidas, rearmadas.

Tabela session_state: snapshot JSON.

Tabela trades (F7b-1): trades fechados.

14.5 — No backtest (engine backtest)
text
backtest_result  n_trades=42 winners=25 losers=17 win_rate=0.5952
                 total_pnl=12345.67 return_pct=12.35 sharpe=1.23
                 max_drawdown_pct=4.56 profit_factor=1.89
14.6 — No shadow (reports/shadow_*.json)
json
{
  "matched": 3, "ea_only": 0, "py_only": 0, "mismatches": 0,
  "total_ea": 3, "total_py": 3, "match_rate": 1.0
}
15. Troubleshooting
15.1 — mt5_indisponivel (IPC failed)
Causa: MT5 não está aberto, ou "Python Integration" desabilitado.

Fix:

Abra o MT5 (demo).

Ferramentas → Opções → Comunidade → "Integração com Python" (marcar).

Reinicie o MT5.

Rode de novo.

15.2 — strategy_resolve_falhou: 'X' não registrada
Causa: --strategies=X com nome que não está no StrategyRegistry.

Fix: use o nome da estratégia (stddev_v510), não o nome do preset (v510_default).

15.3 — uvicorn travado em "Waiting for application startup"
Causa: startup_gateway tentando conectar no MT5 (sem IPC).

Fix: resolva o IPC (15.1) ou use FakeGateway (comentar login no .env).

15.4 — Frontend 404 Not Found em /api/trades ou /api/equity
Causa: os routers não estão incluídos no app.py.

Fix: confirme:

cmd
findstr /C:"include_router" src\engine\web\app.py
Esperado: 6 linhas (status + trades + equity + preset + backtest + shadow + stream).

15.5 — TemplateNotFound no frontend
Causa: template faltando.

Fix: confirme:

cmd
dir src\engine\web\templates\
Esperado: base.html, dashboard.html, _status.html, _status_sse.html, _trades.html, _equity.html, config.html, _preset.html, backtest.html, _backtest.html, shadow.html, _shadow.html.

15.6 — unhashable type: 'dict' no frontend
Causa: TemplateResponse com assinatura antiga (Starlette < 0.30).

Fix: use TemplateResponse(request=request, name="...", context={...}) (kwargs explícitos).

15.7 — httpx2 faltando nos testes
Causa: TestClient precisa do httpx.

Fix: uv pip install httpx + adicionar ao pyproject.toml (extra dev).

15.8 — uvicorn não funciona sem uv run
Fix: sempre uv run uvicorn engine.web.app:app --reload --port 8000.

15.9 — engine.db não persiste
Causa: --db :memory: (SQLite em memória).

Fix: use --db engine.db (padrão).

15.10 — 0 trades no backtest
Causa: CSV com poucos candles (< 180).

Fix: use um CSV com 200+ candles.

15.11 — TypeError no routes/shadow.py (TradeIntent)
Causa: o rascunho do router tentou construir um TradeIntent completo, mas faltaram campos obrigatórios.

Fix: o router corrigido usa _ShadowTrade (duck typing) com apenas bar_time, is_buy e entry_price. Não precisa mexer em nada.

15.12 — uvicorn não fecha com Ctrl+C
Causa: O navegador está com a aba do dashboard aberta, e a conexão SSE (/stream) mantém o servidor ativo.

Fix: Feche a aba do navegador (ou navegue para /config) antes de dar Ctrl+C. Se já travou, aperte Ctrl+C duas vezes.

15.13 — Alterações no /config não refletem no /backtest
Causa: O YAML salvo pelo /config pode estar em cache ou o backtest.py está lendo de settings.preset (default) em vez do app.state.preset_path.

Fix: Edite o YAML manualmente (em presets/stddev_v510_default.yaml) e rode o backtest. Confirme o conteúdo com type presets\stddev_v510_default.yaml | findstr "level_mode sl_points".

15.14 — Backtest "trava" com arquivos muito grandes (> 100k candles)
Causa: O backtester roda no mesmo processo do FastAPI. Arquivos muito grandes (ex: 1M candles) bloqueiam a interface.

Fix: Para arquivos grandes, rode o backtest via CLI (terminal), que é mais rápido e não bloqueia a interface.

15.15 — Gráfico de candles não aparece
Causa: O lightweight-charts.js não foi baixado ou o navegador está com cache.

Fix: Baixe o lightweight-charts.js:

cmd
curl -o src\engine\web\static\lightweight-charts.js https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js
Confirme o tamanho (~160 KB). Depois, recarregue a página com Ctrl+F5.

16. Glossário
Termo	Significado
Região	Área de trade-location criada por um candle-sinal (máx, mín, meio)
Candle-sinal	Candle com z-score de volume ≥ std_ref
Rompimento	Preço cruza a máx (compra) ou a mín (venda) da região
Pullback	Preço retorna ao nível de entrada após o rompimento
Parcial	Saída parcial da posição (tiers 1/2/3)
Reforço	Adicionar contratos no preço de entrada após o preço avançar e voltar
By-risk	Calcular o lote pelo risco (R$ ou % do saldo)
Match rate	Taxa de trades iguais entre EA e Python (0.0 a 1.0)
Drawdown	Queda percentual do equity desde o pico
Sharpe	Retorno ajustado ao risco (anualizado)
Profit factor	Lucro bruto / |prejuízo bruto|
B3Calendar	Calendário de pregões da B3 (feriados 2026-2027)
HTMX	Biblioteca JS (14 KB) que faz AJAX sem escrever JS
Pico.css	CSS semântico (dark mode nativo)
uPlot	Biblioteca de gráficos (50 KB)
Lightweight Charts	Biblioteca de gráficos de candles (45 KB) — F10
Frontend	Dashboard web (FastAPI + HTMX + Pico + uPlot + SSE + Lightweight Charts)
Modo Armadilha	Modo onde a operação é invertida (rompeu p/ cima = venda)
Trap Arm Points	Distância em pontos além do extremo para armar a armadilha
Trap SL Points	Stop Loss do modo armadilha, a partir da entrada
📞 Suporte
Dúvidas sobre o código: leia o AI.md (fonte única de verdade do projeto).

Dúvidas sobre o EA: leia o StdDevVolumeBreakout.mq5 (comentado).

Issues: abra no GitHub.