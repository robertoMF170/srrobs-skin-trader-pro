"""Camada de IA local: comentário qualitativo de tendência via LM Studio.

Complementar ao EV determinístico — nunca o substitui.
"""

from __future__ import annotations

import logging
import statistics

import requests

import config
import db

log = logging.getLogger(__name__)


def _series_stats(conn, name: str) -> dict | None:
    series = db.price_series(conn, name, days=90)
    if len(series) < 5:
        return None
    prices = [p for _, p in series]
    n = len(prices)
    recent = prices[-7:] if n >= 7 else prices
    older = prices[:-7] if n >= 14 else prices[: max(1, n // 2)]
    pct_30 = (
        (prices[-1] - prices[max(0, n // 3)]) / prices[max(0, n // 3)] * 100
        if prices[max(0, n // 3)]
        else 0.0
    )
    return {
        "points": n,
        "min": min(prices),
        "max": max(prices),
        "last": prices[-1],
        "week_avg": statistics.mean(recent),
        "before_avg": statistics.mean(older),
        "pct_recent": (
            (statistics.mean(recent) - statistics.mean(older))
            / statistics.mean(older)
            * 100
            if statistics.mean(older)
            else 0.0
        ),
        "pct_30": pct_30,
        "volatility": statistics.stdev(prices) if n >= 2 else 0.0,
    }


def trend_comment(conn, name: str) -> dict:
    if not config.LMSTUDIO_ENABLED:
        return {"ok": False, "error": "Camada de IA desativada (LMSTUDIO_ENABLED=false)."}
    stats = _series_stats(conn, name)
    if not stats:
        return {"ok": False, "error": "Histórico de preços insuficiente (mín. 5 pontos em 90d)."}
    prompt = (
        f"Skin CS2: {name}\n"
        f"Estatísticas de preço (90 dias): última={stats['last']:.2f}, "
        f"mín={stats['min']:.2f}, máx={stats['max']:.2f}, "
        f"variação 7d vs anterior={stats['pct_recent']:+.1f}%, "
        f"variação ~30d={stats['pct_30']:+.1f}%, "
        f"volatilidade(σ)={stats['volatility']:.2f} {config.CURRENCY}.\n"
        "Escreve 2-3 frases em português de Portugal com um comentário qualitativo "
        "de tendência para um trader (risco de queda/subida, estabilidade). "
        "Sem promessas de lucro. Nota que é uma estimativa qualitativa."
    )
    try:
        resp = requests.post(
            f"{config.LMSTUDIO_BASE_URL}/chat/completions",
            json={
                "model": config.LMSTUDIO_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "És um analista de mercado de skins CS2, conciso e prudente.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens": 220,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        comment = data["choices"][0]["message"]["content"].strip()
        return {"ok": True, "name": name, "comment": comment, "stats": stats}
    except (requests.RequestException, KeyError, IndexError) as exc:
        log.warning("LM Studio falhou: %s", exc)
        return {"ok": False, "error": f"LM Studio indisponível: {exc}"}
