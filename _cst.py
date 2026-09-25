import time

import config

config.setup_logging()
import db
from collectors.steam import SteamCollector

db.init_db()
with db.connect() as conn:
    rows = conn.execute(
        """
        SELECT v.market_hash_name, v.price FROM v_latest_prices v
        JOIN items i ON i.market_hash_name = v.market_hash_name
        WHERE v.source='skinport' AND i.rarity IN ('Restricted','Classified','Covert')
        GROUP BY v.market_hash_name
        ORDER BY MAX(v.price) DESC LIMIT 60
        """
    ).fetchall()
names = [r["market_hash_name"] for r in rows]
print("steam targets:", len(names))
collector = SteamCollector()
collector.max_per_run = 60
points = []
for name in names:
    p = collector._priceoverview(name)
    if p:
        points.append(p)
print("ok:", len(points), "/", len(names))
with db.connect() as conn:
    for p in points:
        db.record_price(conn, market_hash_name=p.market_hash_name, source="steam",
                        price=p.price, currency=p.currency)
print("steam gravados:", len(points))
