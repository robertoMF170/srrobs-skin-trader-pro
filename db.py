import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    market_hash_name TEXT UNIQUE NOT NULL,
    weapon TEXT NOT NULL,
    paint TEXT NOT NULL DEFAULT '',
    wear TEXT NOT NULL,
    rarity TEXT NOT NULL,
    collection TEXT NOT NULL,
    min_float REAL NOT NULL,
    max_float REAL NOT NULL,
    wear_min REAL NOT NULL,
    wear_max REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_rarity ON items(rarity, collection);
CREATE INDEX IF NOT EXISTS idx_items_collection ON items(collection, rarity);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY,
    market_hash_name TEXT NOT NULL,
    source TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    float_value REAL,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ph_name_source_time
    ON price_history(market_hash_name, source, observed_at);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    ev_net REAL NOT NULL,
    roi_pct REAL NOT NULL,
    risk_sd REAL NOT NULL DEFAULT 0,
    robust INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    computed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opp_kind ON opportunities(kind, computed_at);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY,
    market_hash_name TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL,
    purchase_price REAL NOT NULL,
    purchased_at TEXT NOT NULL,
    trade_lock_until TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'locked',
    sold_price REAL,
    suggestion TEXT,
    suggestion_computed_at TEXT,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

BEST_PRICE_VIEW = """
CREATE VIEW IF NOT EXISTS v_latest_prices AS
SELECT ph.market_hash_name, ph.source, ph.price, ph.currency, ph.observed_at
FROM price_history ph
JOIN (
    SELECT market_hash_name, source, MAX(observed_at) AS max_ts
    FROM price_history
    GROUP BY market_hash_name, source
) latest
  ON ph.market_hash_name = latest.market_hash_name
 AND ph.source = latest.source
 AND ph.observed_at = latest.max_ts;
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def open_conn(db_path: str | None = None) -> sqlite3.Connection:
    """Ligação direta (sem context manager) para módulos com ciclo de vida próprio."""
    path = db_path or config.DATABASE_PATH
    _ensure_parent_dir(path)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def connect(db_path: str | None = None):
    path = db_path or config.DATABASE_PATH
    _ensure_parent_dir(path)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.executescript(BEST_PRICE_VIEW)


# --- items ---------------------------------------------------------------


def upsert_item(
    conn: sqlite3.Connection,
    *,
    market_hash_name: str,
    weapon: str,
    paint: str,
    wear: str,
    rarity: str,
    collection: str,
    min_float: float,
    max_float: float,
    wear_min: float,
    wear_max: float,
) -> None:
    conn.execute(
        """
        INSERT INTO items (market_hash_name, weapon, paint, wear, rarity,
                           collection, min_float, max_float, wear_min, wear_max)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(market_hash_name) DO UPDATE SET
            rarity=excluded.rarity,
            collection=excluded.collection,
            min_float=excluded.min_float,
            max_float=excluded.max_float,
            wear_min=excluded.wear_min,
            wear_max=excluded.wear_max
        """,
        (market_hash_name, weapon, paint, wear, rarity, collection,
         min_float, max_float, wear_min, wear_max),
    )


# --- price history ---------------------------------------------------------


def record_price(
    conn: sqlite3.Connection,
    *,
    market_hash_name: str,
    source: str,
    price: float,
    currency: str | None = None,
    float_value: float | None = None,
    observed_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO price_history (market_hash_name, source, price, currency,
                                   float_value, observed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (market_hash_name, source, price, currency or config.CURRENCY,
         float_value, observed_at or utcnow_iso()),
    )


def last_observed(conn: sqlite3.Connection, name: str, source: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(observed_at) AS ts FROM price_history WHERE market_hash_name=? AND source=?",
        (name, source),
    ).fetchone()
    return row["ts"] if row else None


def latest_prices(
    conn: sqlite3.Connection,
    max_age_hours: int | None = None,
    currency: str | None = None,
) -> dict[str, dict[str, dict]]:
    cutoff = None
    if max_age_hours is not None:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    wanted_currency = currency or config.CURRENCY
    sql = "SELECT market_hash_name, source, price, currency, observed_at FROM v_latest_prices"
    rows = conn.execute(sql).fetchall()
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        if cutoff and r["observed_at"] < cutoff:
            continue
        if r["currency"] != wanted_currency:
            continue
        out.setdefault(r["market_hash_name"], {})[r["source"]] = {
            "price": r["price"],
            "currency": r["currency"],
            "observed_at": r["observed_at"],
        }
    return out


def price_series(
    conn: sqlite3.Connection,
    name: str,
    days: int,
    source: str | None = None,
    currency: str | None = None,
) -> list[tuple[str, float]]:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    wanted_currency = currency or config.CURRENCY
    if source:
        rows = conn.execute(
            """
            SELECT observed_at, price FROM price_history
            WHERE market_hash_name=? AND source=? AND observed_at>=? AND currency=?
            ORDER BY observed_at
            """,
            (name, source, cutoff, wanted_currency),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT observed_at, price FROM price_history
            WHERE market_hash_name=? AND observed_at>=? AND currency=?
            ORDER BY observed_at
            """,
            (name, cutoff, wanted_currency),
        ).fetchall()
    return [(r["observed_at"], r["price"]) for r in rows]


# --- opportunities ---------------------------------------------------------


def replace_opportunities(
    conn: sqlite3.Connection, kind: str, rows: list[dict]
) -> None:
    conn.execute("DELETE FROM opportunities WHERE kind=?", (kind,))
    for row in rows:
        conn.execute(
            """
            INSERT INTO opportunities (kind, key, ev_net, roi_pct, risk_sd,
                                       robust, payload, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind,
                row["key"],
                row["ev_net"],
                row["roi_pct"],
                row.get("risk_sd", 0.0),
                1 if row.get("robust") else 0,
                json.dumps(row, ensure_ascii=False),
                utcnow_iso(),
            ),
        )


def list_opportunities(
    conn: sqlite3.Connection, kind: str, robust_only: bool = False
) -> list[dict]:
    sql = "SELECT payload FROM opportunities WHERE kind=?"
    params: list = [kind]
    if robust_only:
        sql += " AND robust=1"
    sql += " ORDER BY ev_net DESC"
    rows = conn.execute(sql, params).fetchall()
    return [json.loads(r["payload"]) for r in rows]


# --- positions -------------------------------------------------------------


def add_position(
    conn: sqlite3.Connection,
    *,
    market_hash_name: str,
    source: str,
    purchase_price: float,
    purchased_at: datetime,
    quantity: int = 1,
    notes: str = "",
) -> int:
    lock_until = purchased_at + timedelta(days=7)
    cur = conn.execute(
        """
        INSERT INTO positions (market_hash_name, quantity, source, purchase_price,
                               purchased_at, trade_lock_until, status, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            market_hash_name,
            quantity,
            source,
            purchase_price,
            purchased_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            lock_until.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "locked",
            notes,
            utcnow_iso(),
        ),
    )
    return cur.lastrowid


# --- settings ---------------------------------------------------------------


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
