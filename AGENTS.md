# AGENTS.md — SrRobs Skin Trader Pro

Este ficheiro define o contrato de desenvolvimento do projeto. Qualquer agente que trabalhe aqui deve seguir estas regras.

## Papel

Engenheiro de software sénior responsável pelo **SrRobs Skin Trader Pro**: dashboard local de análise de skins de CS2 que deteta as oportunidades de trade-up e revenda mais lucrativas, com acesso remoto via Tailscale.

## Objetivo do produto

1. Recolher preços de skins de CS2 em múltiplas fontes (Steam Community Market + marketplaces terceiros).
2. Calcular, de forma determinística, o EV (valor esperado) de todos os trade-ups possíveis com as skins disponíveis nessas fontes.
3. Rankear oportunidades por lucro esperado e robustez face à volatilidade histórica.
4. Permitir comprar diretamente na fonte com um clique (link direto — NUNCA compra automática).
5. Rastrear o trade lock de 7 dias de cada compra e reavaliar o preço no fim do lock (vender / tradear / segurar).

## Stack técnica

- Backend: Python 3.11+, Flask.
- Base de dados: SQLite (caminho aberto para Postgres).
- Scheduler: APScheduler para polling periódico às APIs.
- Frontend: Jinja2 + HTML/CSS/JS puro (sem build step pesado).
- Acesso remoto: `tailscale serve` (privado ao tailnet — NUNCA `funnel`).

## Identidade visual

- Nome: SrRobs Skin Trader Pro.
- Dark mode fixo. Cor de destaque: vermelho (#E63946). Fundo: #0D0D0F / #151517.
- Responsivo, mobile-first — tabelas colapsam em cards abaixo de ~640px.

## Módulos

- `collectors/` — steam.py (priceoverview + pricehistory, throttling agressivo com backoff), csfloat.py (preço + float), skinport.py, dmarket.py. Leituras com timestamp em `price_history` comum.
- `data/items/` — dataset de coleções/raridades/float-ranges de ByMykel/CSGO-API, atualizado periodicamente.
- `engine/tradeup.py` — combinações de 10 skins da mesma raridade, float médio de saída, distribuição de output, EV líquido.
- `engine/risk.py` — desvio-padrão 30/60/90 dias; contratos "robustos" quando EV > ~2x σ (ajustável). UI declara que é estimativa estatística, não garantia.
- `app.py` + `templates/` — ranking por EV/margem com filtro de robustez; botão vermelho "Comprar" → link direto para a fonte; página de posições com contagem decrescente do lock de 7 dias e sugestão vender/tradear/segurar ao expirar.
- Notificações via bot Telegram (Roco): oportunidade acima de threshold e fim de lock.
- Camada de IA local (LM Studio via API OpenAI-compatible): comentário qualitativo de tendência, complementar ao EV determinístico.

## Regras estritas

- NUNCA implementar compra automática — o clique abre sempre nova aba para a fonte; compra é sempre manual.
- NUNCA guardar chaves/cookies no código — usar `.env` + python-dotenv.
- Respeitar rate limits de cada fonte; usar cache local para não repetir pedidos.
- Confirmar que o uso de cada API está dentro dos ToS da plataforma.
- Código modular e testável, com logging estruturado.

## Comandos

- Ambiente: `py -3.11 -m venv .venv` → `.venv\Scripts\pip install -r requirements.txt`.
- Testes: `.venv\Scripts\python -m pytest`.
- Seed de demonstração: `.venv\Scripts\python seed.py`.
- Importar itens reais: `.venv\Scripts\python -m data.importer`.
- Correr: `.venv\Scripts\python app.py` (ou `flask --app app run`).
- Remoto: `tailscale serve --bg 5000` (privado ao tailnet).
