"""Scheduler: polling periódico aos coletores + recomputação de oportunidades."""

from __future__ import annotations

import json
import logging
import random

from apscheduler.schedulers.background import BackgroundScheduler

import config
import db
import notifier
import portfolio
from collectors.csfloat import CsfloatCollector
from collectors.dmarket import DmarketCollector
from collectors.skinport import SkinportCollector
from collectors.steam import SteamCollector
from data.importer import import_items
from engine.opportunities import compute_all

log = logging.getLogger(__name__)


def collect_targets(conn, limit: int = 60) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    rows = conn.execute(
        """
        SELECT payload FROM opportunities
        WHERE ev_net > 0 ORDER BY ev_net DESC LIMIT 100
        """
    ).fetchall()
    for r in rows:
        payload = json.loads(r["payload"])
        candidates = [payload.get("key", "")] + [
            i["name"] for i in payload.get("inputs", [])
        ]
        for c in candidates:
            if c and c not in seen:
                seen.add(c)
                names.append(c)
    if len(names) < limit:
        fallback = conn.execute(
            """
            SELECT v.market_hash_name FROM v_latest_prices v
            JOIN items i ON i.market_hash_name = v.market_hash_name
            GROUP BY v.market_hash_name
            ORDER BY MAX(v.price) DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        for r in fallback:
            if r["market_hash_name"] not in seen:
                seen.add(r["market_hash_name"])
                names.append(r["market_hash_name"])
    if not names:
        sample = conn.execute(
            "SELECT market_hash_name FROM items ORDER BY RANDOM() LIMIT ?", (limit,)
        ).fetchall()
        names = [r["market_hash_name"] for r in sample]
    return names[:limit]


def job_collect(source: str) -> None:
    collector_cls = {
        "steam": SteamCollector,
        "csfloat": CsfloatCollector,
        "skinport": SkinportCollector,
        "dmarket": DmarketCollector,
    }.get(source)
    if collector_cls is None:
        log.error("fonte desconhecida: %s", source)
        return
    collector = collector_cls()
    with db.connect() as conn:
        if source == "skinport":
            names = [
                r["market_hash_name"]
                for r in conn.execute(
                    "SELECT market_hash_name FROM items"
                ).fetchall()
            ]
        else:
            names = collect_targets(conn, limit=min(collector.max_per_run, 500))
    collector.collect_and_store(names)


def job_steam_history() -> None:
    if not config.STEAM_COOKIES:
        return
    from datetime import datetime, timedelta, timezone

    collector = SteamCollector()
    collector.min_interval = 20.0
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT market_hash_name FROM v_latest_prices WHERE source='steam' LIMIT 5"
        ).fetchall()
        names = [r["market_hash_name"] for r in rows]
        week_ago = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        recent = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT market_hash_name FROM price_history "
                "WHERE source='steam' AND observed_at >= ?",
                (week_ago,),
            ).fetchall()
        }
    stored = 0
    for name in names:
        if name in recent:
            continue
        history = collector._pricehistory(name)
        if history:
            with db.connect() as conn:
                for ts, price in history[-90:]:
                    db.record_price(
                        conn,
                        market_hash_name=name,
                        source="steam",
                        price=price,
                        observed_at=ts,
                    )
            stored += 1
    if stored:
        log.info("steam pricehistory: %d itens atualizados", stored)


def job_compute() -> None:
    compute_all()
    with db.connect() as conn:
        notifier.notify_new_opportunities(conn)


def job_positions() -> None:
    with db.connect() as conn:
        positions = portfolio.refresh_positions(conn)
        ready = [p for p in positions if p["status"] == "ready"]
        notifier.notify_lock_ends(conn, ready)


def job_import_items() -> None:
    with db.connect() as conn:
        import_items(conn, force_download=True)


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        lambda: job_collect("skinport"), "interval", minutes=20, id="skinport",
        max_instances=1, coalesce=True,
    )
    sched.add_job(
        lambda: job_collect("csfloat"), "interval", minutes=15, id="csfloat",
        max_instances=1, coalesce=True,
    )
    sched.add_job(
        lambda: job_collect("dmarket"), "interval", minutes=15, id="dmarket",
        max_instances=1, coalesce=True,
    )
    sched.add_job(
        lambda: job_collect("steam"), "interval", minutes=30, id="steam",
        max_instances=1, coalesce=True,
    )
    sched.add_job(job_steam_history, "interval", hours=6, id="steam_history",
                  max_instances=1, coalesce=True)
    sched.add_job(job_compute, "interval", minutes=10, id="compute",
                  max_instances=1, coalesce=True)
    sched.add_job(job_positions, "interval", minutes=5, id="positions",
                  max_instances=1, coalesce=True)
    sched.add_job(job_import_items, "interval", days=7, id="import_items",
                  max_instances=1, coalesce=True)
    sched.start()
    log.info("scheduler iniciado: %s", [j.id for j in sched.get_jobs()])
    return sched


if __name__ == "__main__":
    config.setup_logging()
    db.init_db()
    sched = start_scheduler()
    try:
        while True:
            import time

            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
