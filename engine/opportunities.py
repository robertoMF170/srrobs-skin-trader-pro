"""Orquestrador: combina preços frescos + catálogo + risco e persiste oportunidades."""

from __future__ import annotations

import logging

import config
import db
from engine import risk
from engine.tradeup import BUY_SOURCES, generate_contracts, load_catalog

log = logging.getLogger(__name__)

THIRD_PARTY_PAYOUT_FEE = 0.05


def sale_net(source: str, price: float) -> float:
    """Valor líquido de venda numa fonte (Steam ~15%, terceiros ~5% de payout)."""
    fee = config.STEAM_SALE_FEE if source in ("steam", "steam_ref") else THIRD_PARTY_PAYOUT_FEE
    return price * (1 - fee)


def make_proceeds(prices: dict[str, dict[str, dict]]):
    """Função de valor líquido de venda: Steam real → referência Steam → terceiros."""

    def proceeds(name: str) -> tuple[float | None, str | None]:
        srcs = prices.get(name) or {}
        for source in ("steam", "steam_ref"):
            entry = srcs.get(source)
            if entry and entry["price"] > 0:
                return round(sale_net(source, entry["price"]), 2), source
        others = {s: v for s, v in srcs.items() if s not in ("steam", "steam_ref") and v["price"] > 0}
        if others:
            src, val = max(others.items(), key=lambda kv: kv[1]["price"])
            return round(sale_net(src, val["price"]), 2), src
        return None, None

    return proceeds


def compute_tradeups(conn, prices: dict[str, dict[str, dict]]) -> list[dict]:
    catalog = load_catalog(conn, prices)
    proceeds = make_proceeds(prices)
    contracts = generate_contracts(catalog, proceeds)
    for c in contracts:
        risk_sd, coverage = risk.distribution_risk(
            conn, c["distribution"], days=config.RISK_WINDOW_DAYS
        )
        c.update(risk.classify(c["ev_net"], risk_sd, config.RISK_MULTIPLIER, coverage))
    return contracts


def compute_resale(prices: dict[str, dict[str, dict]]) -> list[dict]:
    """Revenda: comprar na third-party mais barata, vender na melhor OUTRA fonte (líquido).

    A compra é sempre num marketplace third-party (BUY_SOURCES) — nunca na Steam.
    `steam_ref` (referência Steam publicada pela Skinport) é apenas proxy da venda.
    """
    rows: list[dict] = []
    for name, srcs in prices.items():
        buyable = {s: v for s, v in srcs.items() if s in BUY_SOURCES and v["price"] > 0}
        if not buyable:
            continue
        buy_source, buy_val = min(buyable.items(), key=lambda kv: kv[1]["price"])
        buy_price = buy_val["price"]
        best_net, sell_source = None, None
        for s, v in srcs.items():
            if s == buy_source or v["price"] <= 0:
                continue
            net = sale_net(s, v["price"])
            if best_net is None or net > best_net:
                best_net, sell_source = net, s
        if best_net is None:
            continue
        best_net = round(best_net, 2)
        margin = round(best_net - buy_price, 2)
        steam_price = (srcs.get("steam") or srcs.get("steam_ref") or {}).get("price")
        rows.append(
            {
                "key": name,
                "name": name,
                "buy_source": buy_source,
                "buy_price": buy_price,
                "sell_source": sell_source,
                "sell_net": best_net,
                "steam_price": steam_price,
                "steam_net": best_net if sell_source in ("steam", "steam_ref") else None,
                "ev_net": margin,
                "roi_pct": round(margin / buy_price * 100, 2) if buy_price > 0 else 0.0,
            }
        )
    return rows


def annotate_resale_risk(conn, rows: list[dict]) -> list[dict]:
    for row in rows:
        sd, n = risk.price_stddev(
            conn, row["key"], days=config.RISK_WINDOW_DAYS, source=row["sell_source"]
        )
        coverage = 1.0 if n >= risk.MIN_POINTS else 0.0
        row.update(
            risk.classify(row["ev_net"], sd, config.RISK_MULTIPLIER, coverage)
        )
    rows.sort(key=lambda r: -r["ev_net"])
    return rows


def compute_all(conn=None) -> dict:
    owns_conn = conn is None
    if owns_conn:
        conn = db.open_conn()
    try:
        prices = db.latest_prices(conn, max_age_hours=config.PRICE_FRESHNESS_HOURS)
        tradeups = compute_tradeups(conn, prices)
        resale = annotate_resale_risk(conn, compute_resale(prices))
        db.replace_opportunities(conn, "tradeup", tradeups)
        db.replace_opportunities(conn, "resale", resale)
        stats = {
            "tradeups": len(tradeups),
            "tradeups_profitable": sum(1 for t in tradeups if t["ev_net"] > 0),
            "tradeups_robust": sum(1 for t in tradeups if t.get("robust")),
            "resale": len(resale),
            "resale_profitable": sum(1 for r in resale if r["ev_net"] > 0),
            "resale_robust": sum(1 for r in resale if r.get("robust")),
        }
        log.info("oportunidades recalculadas %s", stats)
        return stats
    finally:
        if owns_conn:
            conn.commit()
            conn.close()


if __name__ == "__main__":
    config.setup_logging()
    db.init_db()
    print(compute_all())
