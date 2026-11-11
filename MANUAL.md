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
11. [Fase 6 — Operação Real em Demo (F13)](#11-fase-6--operação-real-em-demo-f13)
12. [Calibração (usando o gráfico)](#12-calibração-usando-o-gráfico)
13. [Recursos detalhados](#13-recursos-detalhados)
14. [Como ver ganhos, perdas e métricas](#14-como-ver-ganhos-perdas-e-métricas)
15. [Salvando o trabalho no Git](#15-salvando-o-trabalho-no-git)
16. [Troubleshooting](#16-troubleshooting)
17. [Glossário](#17-glossário)

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
| **tzdata** | Instalado via `uv add tzdata` (necessário para `ZoneInfo` no Windows) |

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
uv add tzdata
Nota: em Linux/Mac (sem MT5), use só [dev,web].

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
Esperado: 7 seções no log (detector, session, entry, stop, take_profit, risk, regions).

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
Esperado: engine_status com conta=0, servidor=FAKE, simbolo=WIN$N e detector com z=... e candle_sinal=....

4.4 — Loop funciona sem MT5?
powershell
uv run engine run --dry-run --fast --max-ticks 10
Esperado: engine_run_max_ticks ticks=11.

5. Frontend web
O que é: dashboard web (FastAPI + HTMX + Pico.css + uPlot + Lightweight Charts) para acompanhar o motor em tempo real, editar o preset, ver trades/equity, rodar backtests e comparar com o EA (shadow).

5.1 — Iniciar o servidor web
powershell
uv run uvicorn engine.web.app:app --reload --port 8000
Pré-requisito: MT5 aberto e logado (demo) antes de rodar o uvicorn. O startup_gateway conecta no MT5.

Abra http://localhost:8000 → dashboard.

5.2 — Telas do frontend
URL	O que mostra
/	Dashboard (status em tempo real via SSE + gráfico de candles + equity curve + tabela de trades)
/config	Edição do preset (formulário com 7 blocos)
/backtest	Backtest (upload CSV + resultado numérico + gráfico de candles com volume e ferramentas)
/shadow	Shadow (comparar com EA — read-only)
/metrics	Métricas Prometheus (formato text/plain, para monitoramento externo via Grafana/Prometheus)
5.3 — Dashboard (/)
3 cards no topo (atualizam a cada 2s via SSE):

Conta: login, servidor, saldo.

Símbolo: candles avaliados, último preço.

Detector: z-score, média, desvio, volume.

Status do Monitoramento:

Tabela com Status, Direção, Candle Gatilho, Máxima/Mínima, Entrada, Stop Loss, Take Profit.

Gráfico de Candles (Lightweight Charts):

Atualiza em tempo real.

Setas roxas (arrowDown) nos candles gatilho.

Permite arrastar para ver o dia anterior (D-1) e o dia atual (D).

Equity Curve (uPlot):

Curva do saldo acumulado ao longo dos trades.

Atualiza a cada 10s.

Últimos Trades (tabela):

Horário, Direção (BUY/SELL/GATILHO), Entrada, Saída, PnL, Motivo.

Atualiza a cada 10s.

5.4 — Config (/config)
Formulário com 7 blocos (Detector, Sessão, Entrada, Stop Loss, Take Profit, Risco, Regiões) + Modo do Gatilho.

Ações:

Salvar preset: valida com pydantic, faz backup .bak, salva YAML.

Recarregar (descarta): descarta edições, recarrega do YAML.

5.5 — Backtest (/backtest)
O que faz: roda o motor sobre um CSV de candles (sem MT5).

Passo a passo:

Clique em "Escolher arquivo" e selecione um CSV (ex: tests/fixtures/sample_bars.csv).

Ajuste o saldo inicial (default: 100.000).

Clique em "Rodar backtest".

O card verde com as métricas aparece no topo.

O gráfico de candles é renderizado abaixo, com setas de compra/venda e círculos de saída.

Use o seletor de timeframe (1M, 5M, 15M, 30M, 4H, D, M).

Shift + arrastar para medir a distância em pontos entre dois níveis.

5.6 — Shadow (/shadow)
O que faz: compara os deals já executados pelo EA (MQL5) com os deals do Python em uma janela de tempo. Read-only (não coloca ordens).

Passo a passo:

Preencha o EA Magic (obrigatório, ex: 20260718).

(Opcional) Preencha o Python Magic.

(Opcional) Ajuste a Duração.

Clique em "Comparar".

6. Fase 1 — Desenvolvimento (sem MT5)
Objetivo: validar a lógica sem tocar em MT5.

6.1 — Rodar o loop com FakeGateway
powershell
uv run engine run --dry-run --fast --max-ticks 100
O FakeGateway gera preços sintéticos. O TradingSession roda igual à produção, mas sem tocar em MT5.

6.2 — O que observar no log
Log	Significado
strategy_registered	Estratégia registrada no StrategyRegistry
strategy_session_created	Sessão criada (1 por estratégia)
engine_run_start	Loop iniciado
breakout	Região rompeu (direção definida)
executor_place_order	Ordem colocada
end_of_day_closed	Fim do dia — posições fechadas
engine_run_max_ticks	Loop encerrado (limite atingido)
7. Fase 2 — Conexão ao MT5 (leitura)
Objetivo: validar que o motor consegue ler conta, barras e preço do MT5 real.

7.1 — Verificar conexão
powershell
uv run engine status
Esperado: engine_status com conta, servidor, saldo, simbolo, candles e detector.

8. Fase 3 — Loop real em demo
Objetivo: rodar o motor em tempo real contra a conta demo, colocando ordens de verdade (mas em demo).

8.1 — Rodar o loop
powershell
uv run engine run --demo --db engine_demo.db --poll-interval 2
Flags:

--demo: usa RealMT5Gateway (conexão real).

--db engine_demo.db: SQLite separado.

--poll-interval 2: 1 iteração a cada 2 segundos.

8.2 — O que observar
No log:

text
engine_run_start   symbol=WINZ26 dry_run=False n_strategies=1
breakout           bar_time=... is_buy=True stop=800.0 tp=1700.0
executor_place_order  is_buy=True volume=6 price=1100 retcode=10009 ok=True
No MT5 (aba "Trade"): ordens pendentes (BuyLimit/SellLimit) e posições.

No engine_demo.db: regiões, estado da sessão e trades fechados.

8.3 — Parar o loop
Pressione Ctrl+C. O motor salva o estado e fecha o SQLite.

9. Fase 4 — Modo sombra (comparar com o EA)
Objetivo: rodar o motor Python em paralelo ao EA v4.60 (no mesmo MT5) e comparar as decisões.

9.1 — Rodar o shadow
powershell
uv run engine shadow --ea-magic 20260718 --duration 30 --poll-interval 2
9.2 — Analisar o relatório
powershell
type reports\shadow_*.json
Interpretar:

Campo	Significado	Meta
match_rate	matched / max(total_ea, total_py)	> 0.95 (ideal 1.0)
matched	Trades iguais	Alto
ea_only	Trades que EA fez e Python não	Baixo
py_only	Trades que Python fez e EA não	Baixo
mismatches	Ambos fizeram, mas com preço/direção diferentes	Baixo
10. Fase 5 — Backtest (sem MT5)
Objetivo: rodar backtest sobre um CSV de candles, sem MT5.

10.1 — Rodar o backtest
powershell
uv run engine backtest --csv meu_historico.csv
Flags:

--csv: caminho do CSV (obrigatório).

--preset: preset (default: o do .env).

--from-date 2026-01-01: filtra candles a partir de.

--to-date 2026-12-31: filtra candles até.

--initial-balance 100000: saldo inicial.

--slippage 2: slippage em pontos.

--spread 1: spread em pontos.

--output result.json: salva resultado em JSON.

10.2 — O que observar
text
backtest_result  preset=v510_default n_bars=10000 start=2026-01-01T09:00:00
                 end=2026-12-30T17:30:00 n_trades=42 winners=25 losers=17
                 win_rate=0.5952 total_pnl=12345.67 return_pct=12.35
                 sharpe=1.23 max_drawdown_pct=4.56 profit_factor=1.89
11. Fase 6 — Operação Real em Demo (F13)
Objetivo: rodar o motor na conta demo com os parâmetros validados, monitorando em tempo real.

11.1 — Preparação (Véspera)
Abra o MT5 e faça login na conta demo.

Confirme que o símbolo está no Market Watch (WINZ26).

Edite o YAML (presets/stddev_v510_default.yaml) com os parâmetros validados.

Teste a conexão: uv run engine status.

11.2 — Início da Operação
Terminal 1 (Motor):

powershell
cd /d "D:\PycharmProjetos\Cherry_Python\trading-engine-F0 (1)\trading-engine"
uv run engine run --demo --symbols=WINZ26 > logs_demo.txt 2>&1
(O > logs_demo.txt 2>&1 salva todo o log no arquivo e libera o terminal).

Terminal 2 (Dashboard):

powershell
cd /d "D:\PycharmProjetos\Cherry_Python\trading-engine-F0 (1)\trading-engine"
uv run uvicorn engine.web.app:app --port 8000
Abra no navegador: http://localhost:8000.

11.3 — Acompanhamento
No MT5 (aba "Trade"): veja as ordens sendo abertas (pendentes e a mercado).

No Dashboard: acompanhe o gráfico em tempo real, os gatilhos roxos, o Z-score e a tabela de status.

No log (logs_demo.txt): acompanhe os eventos (region_created, breakout, executor_place_order).

11.4 — Como parar
Pare o Dashboard: Ctrl+C no terminal do Uvicorn.

Pare o Motor: Ctrl+C no terminal onde o engine run está rodando.

Zere o MT5: feche as posições e cancele as ordens pendentes.

Se o Ctrl+C não funcionar: use taskkill /F /IM python.exe /T no CMD.

11.5 — Avisos Importantes
Modo Trap: Se estiver usando trigger_mode: trap, o motor vai inverter as operações. No backtest, o modo trap gerou -82% de retorno. Não use em conta real sem validar em demo por 1 mês.

Fuso Horário: O Dashboard pode exibir horários errados nos trigger_candles (ex: 03:03 em vez de 09:03). Ver seção de Troubleshooting.

Trava Anti-Spam: O robô não vai mandar a mesma ordem duas vezes. Se o preço ficar oscilando no gatilho, ele ignora (comportamento correto).

Warm-up Histórico: Ao ligar o motor, ele puxa os 2 últimos dias de candles e salva os gatilhos no banco. Os gatilhos do dia anterior vão aparecer roxos no gráfico.

12. Calibração (usando o gráfico)
O que fazer com o resultado do backtest?

Abra o gráfico em /backtest (após rodar o backtest).

Observe os markers (setas verdes/vermelhas e círculos de saída).

Use a ferramenta de medição (Shift + arrastar) para ver a distância em pontos.

Ajuste o entry.level_mode:

broken_extreme: entrada no rompimento (pullback raso).

default: entrada no meio da região.

immediate: entrada a mercado no instante do rompimento.

Teste novamente com o mesmo CSV e compare os resultados.

Dica: Use o seletor de timeframe (1M, 5M, 15M, etc) para ver o padrão em diferentes escalas.

13. Recursos detalhados
13.1 — engine status
Lê a conta, símbolo, últimos 180 candles, e calcula o z-score do último candle. Não coloca ordens.

13.2 — engine check-config
Valida o preset YAML (pydantic). Não conecta em MT5.

13.3 — engine run
Loop real (dry-run, demo ou real).

13.4 — engine shadow
Modo sombra (compara com o EA).

13.5 — engine backtest
Backtest sobre CSV.

13.6 — Frontend (uvicorn)
Dashboard + config + backtest + shadow.

13.7 — Parciais (tiers 1/2/3)
Divide a saída da posição em 3 partes.

13.8 — Reforço
Adiciona contratos no preço de entrada após o preço avançar e voltar.

13.9 — By-risk sizing
Calcula o lote pelo risco.

13.10 — Calendário B3
Validade de regiões por pregões reais.

13.11 — Multi-estratégia
Roda N estratégias no mesmo motor.

13.12 — Multi-símbolo (F11)
Roda em N símbolos via --symbols.

13.13 — Observabilidade (F12)
Métricas Prometheus no endpoint /metrics.

13.14 — Trava Anti-Spam (F13)
Impede ordens duplicadas. Fica no _make_intent.

13.15 — Warm-up Histórico (F13)
Puxa os 2 últimos dias de candles e salva os gatilhos no banco.

13.16 — Gatilhos Roxos (F13)
Pinta setas roxas (arrowDown) nos candles gatilho.

14. Como ver ganhos, perdas e métricas
14.1 — No frontend
Card de status: conta, símbolo, detector.

Gráfico de Candles: em tempo real, com gatilhos roxos.

Equity Curve: curva do saldo acumulado.

Últimos Trades: tabela com PnL.

Backtest: métricas completas e retorno.

14.2 — No log do engine run
Log estruturado (structlog) mostra cada ordem e cada evento.

14.3 — No MT5 (aba "Trade")
Posições: posições abertas.

Histórico: trades fechados.

Ordens: ordens pendentes.

14.4 — No SQLite (engine.db)
Use DB Browser for SQLite para abrir engine.db:

Tabela regions: regiões ativas.

Tabela session_state: snapshot JSON.

Tabela trades: trades fechados e trigger_candle.

15. Salvando o trabalho no Git
Sempre que fizer uma alteração importante (ou no fim do dia), salve no Git:

powershell
git add .
git commit -m "feat(F13): operacao demo, trava anti-spam e dashboard em tempo real"
git push origin main
Se quiser criar uma versão "congelada" para poder voltar depois:

powershell
git tag -a v0.2.0 -m "Versao com dashboard ao vivo e gatilhos roxos"
git push origin v0.2.0
16. Troubleshooting
16.1 — mt5_indisponivel (IPC failed)
Causa: MT5 não está aberto, ou "Python Integration" desabilitado.
Fix: Abra o MT5, vá em Ferramentas → Opções → Comunidade → "Integração com Python" (marcar). Reinicie o MT5.

16.2 — strategy_resolve_falhou: 'X' não registrada
Causa: --strategies=X com nome que não está no StrategyRegistry.
Fix: use o nome da estratégia (stddev_v510), não o nome do preset (v510_default).

16.3 — uvicorn travado em "Waiting for application startup"
Causa: startup_gateway tentando conectar no MT5 (sem IPC).
Fix: resolva o IPC ou use FakeGateway (comentar login no .env).

16.4 — Frontend 404 Not Found em /api/trades ou /api/equity
Causa: os routers não estão incluídos no app.py.
Fix: confirme: findstr /C:"include_router" src\engine\web\app.py.

16.5 — TemplateNotFound no frontend
Causa: template faltando.
Fix: confirme: dir src\engine\web\templates\.

16.6 — unhashable type: 'dict' no frontend
Causa: TemplateResponse com assinatura antiga.
Fix: use TemplateResponse(request=request, name="...", context={...}).

16.7 — httpx2 faltando nos testes
Causa: TestClient precisa do httpx.
Fix: uv pip install httpx + adicionar ao pyproject.toml (extra dev).

16.8 — engine.db não persiste
Causa: --db :memory:.
Fix: use --db engine.db (padrão).

16.9 — 0 trades no backtest
Causa: CSV com poucos candles (< 180).
Fix: use um CSV com 200+ candles.

16.10 — uvicorn não fecha com Ctrl+C
Causa: O navegador está com a aba do dashboard aberta, e a conexão SSE (/stream) mantém o servidor ativo.
Fix: Feche a aba do navegador (ou navegue para /config) antes de dar Ctrl+C. Se já travou, aperte Ctrl+C duas vezes.

16.11 — Alterações no /config não refletem no /backtest
Causa: O YAML salvo pelo /config pode estar em cache.
Fix: Edite o YAML manualmente e rode o backtest.

16.12 — Backtest "trava" com arquivos grandes (> 100k candles)
Causa: O backtester roda no mesmo processo do FastAPI.
Fix: Rode o backtest via CLI.

16.13 — Gráfico de candles não aparece
Causa: O lightweight-charts.js não foi baixado ou o navegador está com cache.
Fix: Baixe o lightweight-charts.js e recarregue com Ctrl+F5.

16.14 — [Invalid expiration] no MT5
Causa: A Clear Investimentos não aceita ORDER_TIME_GTC para o WINZ26.
Fix: Alterar o gateway.py para usar ORDER_TIME_DAY.

16.15 — Ordens duplicadas (spam)
Causa: O motor não tinha trava anti-spam e mandava a mesma ordem várias vezes por segundo.
Fix: A Trava Anti-Spam está em _make_intent. Se você removeu, recoloque.

16.16 — ModuleNotFoundError: No module named 'tzdata'
Causa: O Windows não tem a base de fusos horários do Python.
Fix: uv add tzdata e reinicie o Uvicorn.

16.17 — Fuso Horário (Dashboard vs MT5)
Causa: O servidor da Clear envia os candles em UTC, e as camadas de conversão (gateway.py + trades.py) estão subtraindo horas em dobro. O Dashboard exibe 03:03 em vez de 09:03.
Fix (pendente): Reverter o gateway.py para salvar em UTC puro; no trades.py, usar o horário bruto do banco; descobrir o offset exato do servidor da Clear.

16.18 — Fuso horário no logs_demo.txt
Causa: O log mostra o horário UTC (que é 3h adiantado em relação a Brasília).
Fix: No arquivo src/engine/infrastructure/logging/setup.py, use utc=False no TimeStamper.

17. Glossário
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
Lightweight Charts	Biblioteca de gráficos de candles (160 KB) — F10
Frontend	Dashboard web (FastAPI + HTMX + Pico + uPlot + SSE + Lightweight Charts)
Modo Armadilha	Modo onde a operação é invertida (rompeu p/ cima = venda)
Trap Arm Points	Distância em pontos além do extremo para armar a armadilha
Trap SL Points	Stop Loss do modo armadilha, a partir da entrada
Trava Anti-Spam	Impede que o motor envie a mesma ordem várias vezes por segundo (F13)
Warm-up Histórico	Puxa 2 dias de candles e salva os gatilhos no banco (F13)
Trigger Candle	Registro no banco que pinta a seta roxa no gráfico (F13)
📞 Suporte
Dúvidas sobre o código: leia o AI.md (fonte única de verdade do projeto).

Dúvidas sobre o EA: leia o StdDevVolumeBreakout.mq5 (comentado).

Issues: abra no GitHub.