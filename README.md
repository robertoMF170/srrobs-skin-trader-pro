# SrRobs Skin Trader Pro

Dashboard local de análise de skins de CS2: deteta as oportunidades de **trade-up** e
**revenda** mais lucrativas entre a Steam Community Market e marketplaces terceiros
(CSFloat, Skinport, DMarket), com EV determinístico, classificação de robustez por
volatilidade histórica, rastreio do trade lock de 7 dias e acesso remoto via Tailscale.

> ⚠️ Ferramenta **estatística de apoio à decisão**. EV e robustez são estimativas, não
> garantias — os preços podem mover-se durante o lock. A compra é **sempre manual**:
> o botão "Comprar" abre a listagem na fonte, numa nova aba. Nunca há compra automática.

## Arquitetura

```
app.py                  Flask: dashboard, posições, itens, API JSON
scheduler.py            APScheduler: polling periódico às fontes + recomputação
db.py                   SQLite (WAL) — schema, price_history, oportunidades, posições
config.py               .env + python-dotenv, logging estruturado (JSON)
collectors/
  base.py               Rate-limit, backoff exponencial, retries 429/5xx
  steam.py              priceoverview (+ pricehistory opcional com cookies)
  csfloat.py            listings: preço + float real das listings
  skinport.py           /v1/items (bulk, sem chave)
  dmarket.py            market/items com assinatura HMAC-SHA256
engine/
  tradeup.py            Matemática do trade-up (float ratio, mix de coleções, EV)
  risk.py               σ 30/60/90d, cobertura de histórico, classificação robusta
  opportunities.py      Orquestrador: preços frescos → contratos + revendas → DB
data/importer.py        Dataset ByMykel/CSGO-API (coleções, raridades, float ranges)
portfolio.py            Posições: lock 7 dias, sugestão vender/tradear/segurar
notifier.py             Telegram (bot Roco): oportunidades robustas + fim de lock
insights.py             IA local opcional (LM Studio): comentário de tendência
seed.py                 Dados de demonstração (testar sem recolha real)
```

## Setup

Requisitos: Python 3.11+ e Tailscale (já instalado na máquina).

```powershell
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env   # e preenche as chaves que tiveres
```

### Primeira execução (com dados de demonstração)

```powershell
.venv\Scripts\python seed.py
.venv\Scripts\python app.py
```

Abre http://localhost:5000 — o seed cria 18 skins fictícias em 2 coleções, histórico
sintético de 90 dias, 2 posições (uma ainda em lock) e oportunidades já rankeadas.

### Uso real

```powershell
.venv\Scripts\python -m data.importer      # importa ~2000 skins reais do ByMykel/CSGO-API
.venv\Scripts\python app.py                # arranca com o scheduler ativo (RUN_SCHEDULER=true)
```

No dashboard, usa os botões **Steam / Skinport / CSFloat / DMarket** para a primeira
recolha manual de preços e **↻ Recalcular** para recomputar as oportunidades. A partir
daí o scheduler faz polling periódico (Skinport 20min, CSFloat/DMarket 15min, Steam
30min + histórico 6h) e revalida a cada 10min.

### Testes

```powershell
.venv\Scripts\python -m pytest
```

## Configuração (`.env`)

Copia de `.env.example`. Pontos importantes:

| Chave | Notas |
|---|---|
| `CURRENCY` | **Uma moeda para tudo** (default `EUR`). O CSFloat devolve USD — leituras noutra moeda são gravadas mas ignoradas pelo motor (filtra por `currency`). |
| `STEAM_COOKIES` | Cookie `SteamLoginSecure=...` do browser com sessão. **Efetivamente obrigatório**: a Steam responde 429 ao `priceoverview` anónimo. Também alimenta o `pricehistory` (histórico real para o motor de risco). |
| `CSFLOAT_API_KEY` | Conta CSFloat → definições de API. |
| `DMARKET_PUBLIC_KEY` / `DMARKET_SECRET_KEY` | DMarket → developer settings. Pedidos assinados HMAC. |
| `SKINPORT_API_KEY` | Opcional (endpoint público funciona sem chave). |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Bot Roco. Avisa de oportunidades robustas ≥ `NOTIFY_MIN_EV` e do fim de locks. |
| `RISK_MULTIPLIER` | Contrato "robusto" = EV ≥ múltiplo × σ (default 2). |
| `LMSTUDIO_ENABLED` | Ativa o comentário de tendência via LM Studio (`LMSTUDIO_BASE_URL`, `LMSTUDIO_MODEL`). Botão "IA" na página Itens. |

Nunca faças commit do `.env` (está no `.gitignore`).

## Como o motor funciona

**Trade-up** (`engine/tradeup.py`) — replica a mecânica oficial:
1. Contratos = 10 inputs da mesma raridade; cada input é a listagem mais barata entre fontes.
2. Combinações: 10× de uma coleção + mixes `k×A + (10−k)×B` (k=1..9) das coleções com stock.
3. Float de saída = `min_out + r̄ × (max_out − min_out)`, com `r̄` = média dos wear-ratios
   normalizados dos inputs (usa o **float real** da listing quando o CSFloat o fornece).
4. Coleção de saída proporcional ao mix; cada skin do tier seguinte equiprovável dentro
   da coleção; o wear do output decide a variante precificada.
5. EV líquido = Σ p(out) × valor líquido de venda − custo dos 10 inputs. Venda assumida
   na Steam (−15%, ajustável) com fallback para terceiros (−5%).

**Risco** (`engine/risk.py`) — σ do preço nos últimos N dias (`RISK_WINDOW_DAYS`, default 30).
Robusto quando EV ≥ `RISK_MULTIPLIER` × σ ponderada do output e há histórico suficiente
(≥3 pontos, cobertura ≥50% da distribuição). Sem histórico suficiente: badge
"dados insuf." — nunca assume robustez.

**Revenda** — compra na fonte mais barata, venda na Steam: margem = preço Steam líquido −
preço de compra, mesma regra de robustez.

**Posições** — registas a compra; lock conta 7 dias. Ao expirar, o dashboard recalcula o
valor líquido atual vs. custo e sugere **vender** (margem ≥ `MIN_SELL_MARGIN_PCT`),
**tradear** (o item é input de trade-ups +EV) ou **segurar**.

## Acesso remoto (Tailscale, privado ao tailnet)

```powershell
tailscale serve --bg 5000
```

O dashboard fica em `https://bot-radar.<tailnet>.ts.net` apenas para os teus dispositivos
do tailnet. **Não usar `funnel`** — exporia publicamente. Para desligar:
`tailscale serve --bg off`.

## ToS e limites das fontes

- **Steam**: `priceoverview`/`pricehistory` são endpoints públicos mas com rate-limit
  agressivo (throttle 3.5s/pedido, backoff em 429, máx. `STEAM_MAX_PER_RUN`/execução).
- **Skinport**: API pública documentada, 8 pedidos/5min (usamos 1 bulk/20min).
- **CSFloat / DMarket**: APIs oficiais com chave, dentro dos limites documentados.
- Dataset de itens: [ByMykel/CSGO-API](https://github.com/ByMykel/CSGO-API) (MIT).

Se uma fonte não tiver chaves configuradas, o coletor regista warning e segue; o motor
funciona com as fontes que tiverem preços na moeda configurada.

## Estrutura da base de dados

SQLite em `data/trader.db` (WAL; caminho aberto para Postgres — toda a persistência
passa por `db.py`). Tabelas: `items`, `price_history`, `opportunities`, `positions`,
`settings` + vista `v_latest_prices` (última leitura por item/fonte).
