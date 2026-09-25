from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import quote

from flask import Flask, jsonify, redirect, render_template, request, url_for

import config
import db
import insights
import portfolio
import scheduler as scheduler_mod
from collectors.csfloat import CsfloatCollector
from collectors.dmarket import DmarketCollector
from collectors.skinport import SkinportCollector
from collectors.steam import SteamCollector
from engine.opportunities import compute_all

log = logging.getLogger(__name__)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
app.jinja_env.globals["APP_NAME"] = "SrRobs Skin Trader Pro"
app.jinja_env.globals["CURRENCY"] = config.CURRENCY
app.jinja_env.globals["LMSTUDIO_ENABLED"] = config.LMSTUDIO_ENABLED

_sched = None

BUY_LINKS = {
    "steam": lambda q, name: f"https://steamcommunity.com/market/listings/730/{q}",
    "skinport": lambda q, name: f"https://skinport.com/market?search={q}",
    "dmarket": lambda q, name: f"https://dmarket.com/ingame-items/item-list/csgo-skins?title={q}",
}

SRC_LABELS = {
    "steam": "Steam",
    "steam_ref": "Steam (ref.)",
    "skinport": "Skinport",
    "csfloat": "CSFloat",
    "dmarket": "DMarket",
}

from engine.tradeup import WEAR_BUCKETS  # noqa: E402


def _csfloat_link(name: str) -> str:
    import json as _json

    wear_range = None
    for wear, lo, hi in WEAR_BUCKETS:
        if name.endswith(f"({wear})"):
            wear_range = [lo, hi]
            break
    filt = {"marketHashName": name, "category": 1}
    if wear_range:
        filt["wear"] = wear_range
    return "https://csfloat.com/?filter=" + quote(_json.dumps(filt, separators=(",", ":")))


@app.context_processor
def inject_helpers():
    def buy_link(source: str, name: str) -> str:
        if source == "csfloat":
            return _csfloat_link(name)
        builder = BUY_LINKS.get(source)
        return builder(quote(name), name) if builder else "#"

    def src_label(source: str) -> str:
        return SRC_LABELS.get(source, source)

    def money(value) -> str:
        if value is None:
            return "—"
        return f"{value:,.2f}".replace(",", " ").replace(".", ",") + f" {config.CURRENCY}"

    def pct(value) -> str:
        return "—" if value is None else f"{value:+.1f}%"

    def wear_short(wear: str) -> str:
        return {
            "Factory New": "FN",
            "Minimal Wear": "MW",
            "Field-Tested": "FT",
            "Well-Worn": "WW",
            "Battle-Scarred": "BS",
        }.get(wear, wear)

    return dict(
        buy_link=buy_link,
        src_label=src_label,
        money=money,
        pct=pct,
        wear_short=wear_short,
    )


@app.before_request
def init_on_first_hit():
    db.init_db()


@app.route("/")
def dashboard():
    max_cost = request.args.get("max_cost", type=float)
    min_ev = request.args.get("min_ev", type=float, default=0.0) or 0.0
    robust_only = request.args.get("robust", "0") == "1"

    def apply_filters(rows, cost_key):
        if robust_only:
            rows = [r for r in rows if r.get("robust")]
        if min_ev > 0:
            rows = [r for r in rows if r.get("ev_net", 0) >= min_ev]
        if max_cost is not None:
            rows = [r for r in rows if r.get(cost_key, float("inf")) <= max_cost]
        return rows

    with db.connect() as conn:
        tradeups = db.list_opportunities(conn, "tradeup")
        resale = db.list_opportunities(conn, "resale")
        last_compute = conn.execute(
            "SELECT MAX(computed_at) AS ts FROM opportunities"
        ).fetchone()["ts"]
        items_count = conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
        prices_count = conn.execute(
            "SELECT COUNT(*) AS c FROM price_history"
        ).fetchone()["c"]
    return render_template(
        "index.html",
        tradeups=apply_filters(tradeups, "cost")[:100],
        resale=apply_filters(resale, "buy_price")[:100],
        tradeup_total=len(tradeups),
        tradeup_robust_total=sum(1 for t in tradeups if t.get("robust")),
        resale_total=len(resale),
        resale_profitable_total=sum(1 for r in resale if r.get("ev_net", 0) > 0),
        last_compute=last_compute,
        items_count=items_count,
        prices_count=prices_count,
        f_max_cost="" if max_cost is None else int(max_cost) if max_cost == int(max_cost) else max_cost,
        f_min_ev=min_ev,
        f_robust=robust_only,
    )


@app.route("/api/opportunities")
def api_opportunities():
    kind = request.args.get("kind", "tradeup")
    robust_only = request.args.get("robust", "0") == "1"
    min_ev = request.args.get("min_ev", type=float, default=None)
    limit = min(request.args.get("limit", 100, type=int), 500)
    if kind not in ("tradeup", "resale"):
        return jsonify({"error": "kind inválido"}), 400
    with db.connect() as conn:
        rows = db.list_opportunities(conn, kind, robust_only=robust_only)
    if min_ev is not None:
        rows = [r for r in rows if r.get("ev_net", 0) >= min_ev]
    return jsonify(rows[:limit])


@app.route("/positions")
def positions_page():
    with db.connect() as conn:
        rows = portfolio.refresh_positions(conn)
    return render_template("positions.html", positions=rows)


@app.route("/api/positions")
def api_positions():
    with db.connect() as conn:
        rows = portfolio.refresh_positions(conn)
    return jsonify(rows)


@app.route("/positions/add", methods=["POST"])
def positions_add():
    name = request.form.get("name", "").strip()
    source = request.form.get("source", "steam").strip()
    price_raw = request.form.get("purchase_price", "").replace(",", ".")
    qty_raw = request.form.get("quantity", "1")
    purchased_raw = request.form.get("purchased_at", "").strip()
    notes = request.form.get("notes", "").strip()
    if not name or not price_raw:
        return redirect(url_for("positions_page"))
    try:
        price = float(price_raw)
        qty = max(1, int(qty_raw or 1))
    except ValueError:
        return redirect(url_for("positions_page"))
    purchased_at = datetime.now(timezone.utc)
    if purchased_raw:
        try:
            purchased_at = datetime.fromisoformat(purchased_raw).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass
    with db.connect() as conn:
        db.add_position(
            conn,
            market_hash_name=name,
            source=source,
            purchase_price=price,
            purchased_at=purchased_at,
            quantity=qty,
            notes=notes,
        )
    return redirect(url_for("positions_page"))


@app.route("/positions/<int:pos_id>/status", methods=["POST"])
def positions_status(pos_id: int):
    action = request.args.get("action", "")
    sold_price_raw = request.form.get("sold_price", "").replace(",", ".")
    if action not in ("sold", "held", "retraded"):
        return redirect(url_for("positions_page"))
    sold_price = None
    if action == "sold" and sold_price_raw:
        try:
            sold_price = float(sold_price_raw)
        except ValueError:
            sold_price = None
    with db.connect() as conn:
        conn.execute(
            "UPDATE positions SET status=?, sold_price=? WHERE id=?",
            (action, sold_price, pos_id),
        )
    return redirect(url_for("positions_page"))


@app.route("/positions/<int:pos_id>/delete", methods=["POST"])
def positions_delete(pos_id: int):
    with db.connect() as conn:
        conn.execute("DELETE FROM positions WHERE id=?", (pos_id,))
    return redirect(url_for("positions_page"))


@app.route("/items")
def items_page():
    q = request.args.get("q", "").strip()
    rows = []
    with db.connect() as conn:
        prices = db.latest_prices(conn, max_age_hours=config.PRICE_FRESHNESS_HOURS)
        if q:
            rows = conn.execute(
                """
                SELECT * FROM items WHERE market_hash_name LIKE ?
                ORDER BY rarity, collection, weapon, wear LIMIT 200
                """,
                (f"%{q}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT i.* FROM items i
                JOIN v_latest_prices v ON v.market_hash_name = i.market_hash_name
                GROUP BY i.market_hash_name
                ORDER BY MAX(v.observed_at) DESC LIMIT 100
                """
            ).fetchall()
    items = []
    for r in rows:
        sources = prices.get(r["market_hash_name"], {})
        buyable = {
            s: v for s, v in sources.items() if s in ("skinport", "csfloat", "dmarket")
        }
        best_source = (
            min(buyable, key=lambda s: buyable[s]["price"]) if buyable else None
        )
        items.append(
            {
                "row": r,
                "sources": sources,
                "best_source": best_source,
                "best_price": buyable[best_source]["price"] if best_source else None,
            }
        )
    return render_template("items.html", items=items, q=q)


@app.route("/collect/<source>", methods=["POST"])
def run_collect(source: str):
    collector = {
        "steam": SteamCollector,
        "csfloat": CsfloatCollector,
        "skinport": SkinportCollector,
        "dmarket": DmarketCollector,
    }.get(source)
    if collector is None:
        return jsonify({"error": "fonte desconhecida"}), 400
    extra = request.form.get("name", "").strip()
    inst = collector()
    with db.connect() as conn:
        from scheduler import collect_targets

        names = collect_targets(conn, limit=min(inst.max_per_run, 300))
    if extra:
        names = [extra] + [n for n in names if n != extra]
    stored = inst.collect_and_store(names)
    return jsonify({"source": source, "stored": stored})


@app.route("/compute", methods=["POST"])
def run_compute():
    stats = compute_all()
    return jsonify(stats)


@app.route("/api/ai/trend", methods=["POST"])
def ai_trend():
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "nome em falta"}), 400
    with db.connect() as conn:
        result = insights.trend_comment(conn, name)
    status = 200 if result.get("ok") else 503
    return jsonify(result), status


@app.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "scheduler": _sched is not None and _sched.running,
            "currency": config.CURRENCY,
        }
    )


def main():
    global _sched
    config.setup_logging()
    db.init_db()
    if config.RUN_SCHEDULER:
        _sched = scheduler_mod.start_scheduler()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
