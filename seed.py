"""Seed de demonstração: itens, histórico sintético de preços e posições de exemplo.

Corre com: .venv\\Scripts\\python seed.py
Permite testar o motor de trade-up e o dashboard sem esperar pela primeira recolha real.
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

import config
import db
from data.importer import market_hash_names

random.seed(42)

# (base_name, weapon, paint, rarity, collection, min_float, max_float,
#  base_price por tier aproximado)
CATALOG = [
    # Coleção "Prima SSA" (fictícia, cadeia consumer→covert)
    ("P250 | Sand Dune",          "P250", "Sand Dune",          "Consumer Grade", "Prima SSA", 0.06, 0.80, 0.10),
    ("MP9 | Sand Dashed",         "MP9", "Sand Dashed",         "Consumer Grade", "Prima SSA", 0.06, 0.80, 0.12),
    ("Nova | Predator",           "Nova", "Predator",           "Industrial Grade", "Prima SSA", 0.06, 0.80, 2.00),
    ("Sawed-Off | Origami",       "Sawed-Off", "Origami",       "Industrial Grade", "Prima SSA", 0.10, 0.26, 2.50),
    ("SG 553 | Wave Spray",       "SG 553", "Wave Spray",       "Mil-Spec Grade", "Prima SSA", 0.00, 0.55, 1.60),
    ("XM1014 | Oxide Blaze",      "XM1014", "Oxide Blaze",      "Mil-Spec Grade", "Prima SSA", 0.00, 0.60, 1.80),
    ("P90 | Ash Wood",            "P90", "Ash Wood",            "Restricted", "Prima SSA", 0.06, 0.80, 5.50),
    ("MAG-7 | Ricochet",          "MAG-7", "Ricochet",          "Restricted", "Prima SSA", 0.00, 0.55, 5.00),
    ("Five-SeveN | Copper Galaxy","Five-SeveN", "Copper Galaxy","Classified", "Prima SSA", 0.00, 0.70, 80.0),
    ("AK-47 | Slate",             "AK-47", "Slate",             "Classified", "Prima SSA", 0.00, 0.60, 70.0),
    ("AWP | Chromatic Aberration","AWP", "Chromatic Aberration","Covert", "Prima SSA", 0.00, 0.55, 260.0),
    # Coleção "Gamma Danger" (fictícia) para misturas
    ("SCAR-20 | Assault",         "SCAR-20", "Assault",         "Consumer Grade", "Gamma Danger", 0.06, 0.80, 0.09),
    ("Glock-18 | Weasel",         "Glock-18", "Weasel",         "Consumer Grade", "Gamma Danger", 0.06, 0.80, 0.11),
    ("Tec-9 | Remote Control",    "Tec-9", "Remote Control",    "Industrial Grade", "Gamma Danger", 0.06, 0.80, 1.90),
    ("PP-Bizon | Photic Zone",    "PP-Bizon", "Photic Zone",    "Mil-Spec Grade", "Gamma Danger", 0.00, 0.60, 1.70),
    ("G3SG1 | Stinger",           "G3SG1", "Stinger",           "Restricted", "Gamma Danger", 0.00, 0.50, 5.20),
    ("M4A4 | Desert-Strike",      "M4A4", "Desert-Strike",      "Classified", "Gamma Danger", 0.00, 0.55, 75.0),
    ("Desert Eagle | Emerald Code","Desert Eagle","Emerald Code","Covert", "Gamma Danger", 0.00, 0.65, 250.0),
]

# multiplicador de preço por wear (FT ≈ referência)
WEAR_MULT = {
    "Factory New": 2.2,
    "Minimal Wear": 1.5,
    "Field-Tested": 1.0,
    "Well-Worn": 0.8,
    "Battle-Scarred": 0.65,
}

# desconto dos marketplaces terceiros face à Steam
SOURCE_DISCOUNT = {"skinport": 0.72, "csfloat": 0.68, "dmarket": 0.75}


def synth_history(base_price: float, days: int = 95, drift: float = 0.0):
    """Série diária: preço base + tendência + ruído, com volatilidade controlada."""
    out = []
    price = base_price
    now = datetime.now(timezone.utc)
    for i in range(days, -1, -1):
        ts = now - timedelta(days=i)
        noise = random.gauss(0, base_price * 0.015)
        price = max(base_price * 0.4, price * (1 + drift / days + random.gauss(0, 0.006)))
        out.append((ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), price + noise))
    return out


def run() -> None:
    config.setup_logging()
    if os.path.exists(config.DATABASE_PATH):
        os.remove(config.DATABASE_PATH)
    db.init_db()

    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        for base, weapon, paint, rarity, collection, min_f, max_f, price_ft in CATALOG:
            for wear, mhn, wmin, wmax in market_hash_names(base, min_f, max_f):
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
                    wear_min=wmin,
                    wear_max=wmax,
                )
                ref_price = price_ft * WEAR_MULT.get(wear, 1.0)
                drift = random.uniform(-0.08, 0.05)

                steam_price = ref_price * random.uniform(0.97, 1.03)
                for ts, p in synth_history(steam_price, drift=drift):
                    db.record_price(conn, market_hash_name=mhn, source="steam",
                                    price=round(p, 2), observed_at=ts)
                for source, disc in SOURCE_DISCOUNT.items():
                    db.record_price(
                        conn,
                        market_hash_name=mhn,
                        source=source,
                        price=round(ref_price * disc * random.uniform(0.95, 1.05), 2),
                    )

        db.add_position(
            conn,
            market_hash_name="SG 553 | Wave Spray (Field-Tested)",
            source="skinport",
            purchase_price=2.30,
            purchased_at=now - timedelta(days=8),
            quantity=10,
            notes="seed — lock já expirado",
        )
        db.add_position(
            conn,
            market_hash_name="P90 | Ash Wood (Minimal Wear)",
            source="csfloat",
            purchase_price=11.80,
            purchased_at=now - timedelta(days=2),
            quantity=1,
            notes="seed — ainda em lock",
        )

    from engine.opportunities import compute_all

    stats = compute_all()
    print("Seed concluído.")
    print(f"  itens: {len(CATALOG)} skins × wears")
    print(f"  oportunidades: {stats}")


if __name__ == "__main__":
    run()
