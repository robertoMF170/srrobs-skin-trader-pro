import json
import logging
import os
import time

import requests

import config
import db
from engine.tradeup import RARITY_ORDER, wear_ranges

log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "items")
SKINS_URL = (
    "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins.json"
)
COLLECTIONS_URL = (
    "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/collections.json"
)


def _download(url: str, dest: str) -> None:
    log.info("a descarregar %s", url)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(resp.text)
    log.info("gravado em %s (%d bytes)", dest, len(resp.text))


def _collection_map_from_collections(collections: list[dict]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for coll in collections:
        for contains in coll.get("contains", []):
            name = contains.get("name")
            if name:
                mapping[name] = coll.get("name", "")
    return mapping


def market_hash_names(base_name: str, min_float: float, max_float: float):
    for wear, lo, hi in wear_ranges(min_float, max_float):
        yield wear, f"{base_name} ({wear})", lo, hi


def import_items(conn=None, force_download: bool = False) -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    skins_path = os.path.join(DATA_DIR, "skins.json")
    collections_path = os.path.join(DATA_DIR, "collections.json")

    if force_download or not os.path.exists(skins_path):
        _download(SKINS_URL, skins_path)
        time.sleep(1)
        _download(COLLECTIONS_URL, collections_path)

    with open(skins_path, encoding="utf-8") as fh:
        skins = json.load(fh)
    with open(collections_path, encoding="utf-8") as fh:
        collections = json.load(fh)

    fallback_coll = _collection_map_from_collections(collections)

    stats = {"skins": 0, "variants": 0, "skipped": 0}
    owns_conn = conn is None
    if owns_conn:
        conn = db.open_conn()

    try:
        for skin in skins:
            base = skin.get("name", "").strip()
            rarity = (skin.get("rarity") or {}).get("name", "")
            if not base or not rarity:
                stats["skipped"] += 1
                continue
            if rarity not in RARITY_ORDER:
                stats["skipped"] += 1
                continue
            min_f = float(skin.get("min_float") or 0.0)
            max_f = float(skin.get("max_float") or 1.0)
            if max_f <= min_f:
                stats["skipped"] += 1
                continue
            colls = skin.get("collections") or []
            collection = colls[0].get("name", "") if colls else fallback_coll.get(base, "")
            weapon, _, paint = base.partition(" | ")
            stats["skins"] += 1
            for wear, mhn, lo, hi in market_hash_names(base, min_f, max_f):
                db.upsert_item(
                    conn,
                    market_hash_name=mhn,
                    weapon=weapon,
                    paint=paint,
                    wear=wear,
                    rarity=rarity,
                    collection=collection,
                    min_float=min_f,
                    max_float=max_f,
                    wear_min=lo,
                    wear_max=hi,
                )
                stats["variants"] += 1
        db.set_setting(conn, "items_last_import", db.utcnow_iso())
    finally:
        if owns_conn:
            conn.commit()
            conn.close()

    log.info(
        "import concluído: %d skins, %d variantes de wear, %d ignoradas",
        stats["skins"], stats["variants"], stats["skipped"],
    )
    return stats


if __name__ == "__main__":
    config.setup_logging()
    db.init_db()
    with db.connect() as conn:
        print(import_items(conn))
