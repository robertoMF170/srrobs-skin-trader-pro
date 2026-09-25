"""Gestão de posições: trade lock de 7 dias e sugestões vender/tradear/segurar."""

from __future__ import annotations

from datetime import datetime, timezone

import config
import db
from engine.opportunities import make_proceeds


def is_locked(pos) -> bool:
    return db.parse_iso(pos["trade_lock_until"]) > datetime.now(timezone.utc)


def tradeup_input_names(conn) -> set[str]:
    rows = conn.execute(
        """
        SELECT payload FROM opportunities
        WHERE kind='tradeup' AND ev_net > 0
        ORDER BY ev_net DESC LIMIT 200
        """
    ).fetchall()
    import json

    names: set[str] = set()
    for r in rows:
        payload = json.loads(r["payload"])
        for i in payload.get("inputs", []):
            names.add(i["name"])
    return names


def evaluate_suggestion(conn, pos, prices: dict[str, dict[str, dict]]) -> dict:
    """Devolve {estado, sugestão, valor_atual, lucro} para uma posição."""
    now = datetime.now(timezone.utc)
    locked = db.parse_iso(pos["trade_lock_until"]) > now
    proceeds = make_proceeds(prices)
    net, src = proceeds(pos["market_hash_name"])
    cost = pos["purchase_price"] * pos["quantity"]

    if pos["status"] in ("sold", "retraded"):
        state = pos["status"]
        suggestion = pos["status"]
    elif locked:
        state = "locked"
        suggestion = "aguardar_lock"
    else:
        state = "ready"
        if net is not None and net >= cost * (1 + config.MIN_SELL_MARGIN_PCT / 100):
            suggestion = "vender"
        elif pos["market_hash_name"] in tradeup_input_names(conn):
            suggestion = "tradear"
        else:
            suggestion = "segurar"

    return {
        "id": pos["id"],
        "name": pos["market_hash_name"],
        "quantity": pos["quantity"],
        "source": pos["source"],
        "purchase_price": pos["purchase_price"],
        "cost_total": round(cost, 2),
        "purchased_at": pos["purchased_at"],
        "trade_lock_until": pos["trade_lock_until"],
        "status": state,
        "suggestion": suggestion,
        "current_net": net if net is not None else None,
        "current_source": src,
        "current_profit": (
            round(net * pos["quantity"] - cost, 2) if net is not None else None
        ),
        "current_profit_pct": (
            round((net * pos["quantity"] - cost) / cost * 100, 2)
            if net is not None and cost > 0
            else None
        ),
        "notes": pos["notes"],
    }


def refresh_positions(conn) -> list[dict]:
    prices = db.latest_prices(conn, max_age_hours=config.PRICE_FRESHNESS_HOURS)
    rows = conn.execute(
        "SELECT * FROM positions ORDER BY created_at DESC"
    ).fetchall()
    return [evaluate_suggestion(conn, pos, prices) for pos in rows]
