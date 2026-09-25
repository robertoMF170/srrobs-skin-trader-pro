"""Motor determinístico de trade-up contracts (CS2).

Mecânica implementada:
- 10 inputs da mesma raridade; output sobe um tier.
- A coleção do output é sorteada proporcionalmente ao nº de inputs dessa coleção.
- Dentro da coleção, cada skin de output é equiprovável.
- Float do output = min_out + r_medio * (max_out - min_out), onde r_medio é a média
  dos wear-ratios normalizados dos inputs (fórmula oficial do trade-up).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable

WEAR_BUCKETS: list[tuple[str, float, float]] = [
    ("Factory New", 0.00, 0.07),
    ("Minimal Wear", 0.07, 0.15),
    ("Field-Tested", 0.15, 0.38),
    ("Well-Worn", 0.38, 0.45),
    ("Battle-Scarred", 0.45, 1.00),
]

RARITY_ORDER = [
    "Consumer Grade",
    "Industrial Grade",
    "Mil-Spec Grade",
    "Restricted",
    "Classified",
    "Covert",
]

CONTRACT_SIZE = 10

# Fontes onde se compra (third-party). Steam/steam_ref servem apenas de lado da venda.
BUY_SOURCES = ("skinport", "csfloat", "dmarket")


def wear_bucket(float_value: float) -> str:
    for wear, lo, hi in WEAR_BUCKETS:
        if lo <= float_value < hi:
            return wear
    return WEAR_BUCKETS[-1][0] if float_value >= 1.0 else WEAR_BUCKETS[0][0]


def wear_ranges(min_float: float, max_float: float):
    for wear, lo, hi in WEAR_BUCKETS:
        wmin = max(lo, min_float)
        wmax = min(hi, max_float)
        if wmax > wmin:
            yield wear, wmin, wmax


def next_rarity(rarity: str) -> str | None:
    try:
        idx = RARITY_ORDER.index(rarity)
    except ValueError:
        return None
    if idx + 1 >= len(RARITY_ORDER):
        return None
    return RARITY_ORDER[idx + 1]


@dataclass
class InputSkin:
    market_hash_name: str
    weapon: str
    paint: str
    wear: str
    rarity: str
    collection: str
    skin_min: float
    skin_max: float
    wear_min: float
    wear_max: float
    price: float
    source: str
    float_value: float | None = None

    def wear_ratio(self) -> float:
        span = self.skin_max - self.skin_min
        if span <= 0:
            return 0.5
        if self.float_value is not None:
            fv = min(max(self.float_value, self.skin_min), self.skin_max)
        else:
            fv = (self.wear_min + self.wear_max) / 2.0
        return (fv - self.skin_min) / span


@dataclass
class OutputSkin:
    base_name: str
    weapon: str
    paint: str
    rarity: str
    collection: str
    skin_min: float
    skin_max: float
    variants: dict[str, str] = field(default_factory=dict)


ProceedsFn = Callable[[str], tuple[float | None, str | None]]


def evaluate_contract(
    inputs: list[InputSkin],
    outputs_by_collection: dict[str, list[OutputSkin]],
    proceeds: ProceedsFn,
) -> dict | None:
    if len(inputs) != CONTRACT_SIZE:
        return None
    avg_ratio = sum(i.wear_ratio() for i in inputs) / len(inputs)
    cost = sum(i.price for i in inputs)
    counts = Counter(i.collection for i in inputs)

    distribution: list[dict] = []
    for collection, n in counts.items():
        outs = outputs_by_collection.get(collection) or []
        if not outs:
            return None
        p_coll = n / CONTRACT_SIZE
        for out in outs:
            prob = p_coll / len(outs)
            out_float = out.skin_min + avg_ratio * (out.skin_max - out.skin_min)
            wear = wear_bucket(out_float)
            name = out.variants.get(wear)
            net = None
            src = None
            if name:
                net, src = proceeds(name)
            if net is None:
                best_net, best_src = None, None
                for variant_name in out.variants.values():
                    v_net, v_src = proceeds(variant_name)
                    if v_net is not None and (best_net is None or v_net > best_net):
                        best_net, best_src = v_net, v_src
                net, src = best_net, best_src
            distribution.append(
                {
                    "base": out.base_name,
                    "name": name or out.base_name,
                    "wear": wear,
                    "float": round(out_float, 5),
                    "prob": prob,
                    "net": net or 0.0,
                    "source": src,
                }
            )

    ev_gross = sum(d["prob"] * d["net"] for d in distribution)
    ev_net = ev_gross - cost
    distribution.sort(key=lambda d: (-d["prob"], -d["net"]))
    mix = " + ".join(
        f"{n}× {coll}" for coll, n in sorted(counts.items(), key=lambda kv: -kv[1])
    )
    top = distribution[0] if distribution else {}
    return {
        "key": "|".join(sorted(i.market_hash_name for i in inputs)),
        "rarity": inputs[0].rarity,
        "mix": mix,
        "collections": dict(counts),
        "avg_ratio": round(avg_ratio, 5),
        "cost": round(cost, 2),
        "ev_gross": round(ev_gross, 2),
        "ev_net": round(ev_net, 2),
        "roi_pct": round(ev_net / cost * 100, 2) if cost > 0 else 0.0,
        "inputs": [
            {
                "name": i.market_hash_name,
                "collection": i.collection,
                "price": i.price,
                "source": i.source,
                "float_value": i.float_value,
            }
            for i in inputs
        ],
        "distribution": [
            {**d, "prob": round(d["prob"], 5)} for d in distribution
        ],
        "top_output": top.get("name", ""),
        "top_output_prob": round(top.get("prob", 0.0), 4),
    }


def generate_contracts(
    catalog_by_rarity: dict[str, tuple[dict[str, list[InputSkin]], dict[str, list[OutputSkin]]]],
    proceeds: ProceedsFn,
    max_contracts: int = 3000,
) -> list[dict]:
    results: list[dict] = []
    for rarity, (inputs_by_collection, outputs_by_collection) in catalog_by_rarity.items():
        pools: dict[str, list[InputSkin]] = {}
        for coll, items in inputs_by_collection.items():
            if outputs_by_collection.get(coll):
                pool = sorted(items, key=lambda i: i.price)[:CONTRACT_SIZE]
                if len(pool) == CONTRACT_SIZE:
                    pools[coll] = pool

        for coll, pool in pools.items():
            contract = evaluate_contract(pool, outputs_by_collection, proceeds)
            if contract:
                contract["key"] = f"{rarity}|single:{coll}"
                results.append(contract)

        for coll_a, coll_b in combinations(sorted(pools), 2):
            for k in range(1, CONTRACT_SIZE):
                inputs = pools[coll_a][:k] + pools[coll_b][: CONTRACT_SIZE - k]
                contract = evaluate_contract(inputs, outputs_by_collection, proceeds)
                if contract:
                    contract["key"] = f"{rarity}|mix:{coll_a}:{k}:{coll_b}"
                    results.append(contract)
            if len(results) >= max_contracts:
                break

    results.sort(key=lambda c: -c["ev_net"])
    return results[:max_contracts]


def load_catalog(
    conn,
    prices: dict[str, dict[str, dict]],
) -> dict[str, tuple[dict[str, list[InputSkin]], dict[str, list[OutputSkin]]]]:
    rows = conn.execute(
        """
        SELECT market_hash_name, weapon, paint, wear, rarity, collection,
               min_float, max_float, wear_min, wear_max
        FROM items
        WHERE collection != '' AND rarity IN ({})
        """.format(",".join("?" * len(RARITY_ORDER))),
        RARITY_ORDER,
    ).fetchall()

    inputs_grouped: dict[tuple[str, str], list[InputSkin]] = {}
    outputs_grouped: dict[tuple[str, str, str], OutputSkin] = {}

    for r in rows:
        base_name = f"{r['weapon']} | {r['paint']}" if r["paint"] else r["weapon"]
        key = (r["collection"], r["rarity"], base_name)
        out = outputs_grouped.get(key)
        if out is None:
            out = OutputSkin(
                base_name=base_name,
                weapon=r["weapon"],
                paint=r["paint"],
                rarity=r["rarity"],
                collection=r["collection"],
                skin_min=r["min_float"],
                skin_max=r["max_float"],
            )
            outputs_grouped[key] = out
        out.variants[r["wear"]] = r["market_hash_name"]

        sources = {
            s: v
            for s, v in (prices.get(r["market_hash_name"]) or {}).items()
            if s in BUY_SOURCES and v["price"] > 0
        }
        if not sources:
            continue
        best_source = min(sources, key=lambda s: sources[s]["price"])
        best = sources[best_source]
        skin = InputSkin(
            market_hash_name=r["market_hash_name"],
            weapon=r["weapon"],
            paint=r["paint"],
            wear=r["wear"],
            rarity=r["rarity"],
            collection=r["collection"],
            skin_min=r["min_float"],
            skin_max=r["max_float"],
            wear_min=r["wear_min"],
            wear_max=r["wear_max"],
            price=best["price"],
            source=best_source,
        )
        inputs_grouped.setdefault((r["rarity"], r["collection"]), []).append(skin)

    catalog: dict[str, tuple[dict, dict]] = {}
    for rarity in RARITY_ORDER:
        nr = next_rarity(rarity)
        if not nr:
            continue
        inputs_by_collection = {
            coll: items
            for (rar, coll), items in inputs_grouped.items()
            if rar == rarity
        }
        if not inputs_by_collection:
            continue
        outputs_by_collection: dict[str, list[OutputSkin]] = {}
        for (coll, out_rarity, _), out in outputs_grouped.items():
            if out_rarity == nr:
                outputs_by_collection.setdefault(coll, []).append(out)
        for outs in outputs_by_collection.values():
            outs.sort(key=lambda o: o.base_name)
        catalog[rarity] = (inputs_by_collection, outputs_by_collection)
    return catalog
