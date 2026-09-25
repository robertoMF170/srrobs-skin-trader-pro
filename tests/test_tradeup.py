from engine.tradeup import (
    CONTRACT_SIZE,
    InputSkin,
    OutputSkin,
    evaluate_contract,
    wear_bucket,
    wear_ranges,
)


def make_input(name, collection, price, skin_min=0.0, skin_max=1.0,
               wear_min=0.15, wear_max=0.38, rarity="Mil-Spec Grade",
               float_value=None, source="skinport", weapon="AK-47", paint="X"):
    return InputSkin(
        market_hash_name=name,
        weapon=weapon,
        paint=paint,
        wear="Field-Tested",
        rarity=rarity,
        collection=collection,
        skin_min=skin_min,
        skin_max=skin_max,
        wear_min=wear_min,
        wear_max=wear_max,
        price=price,
        source=source,
        float_value=float_value,
    )


def make_output(base, collection, variants, skin_min=0.0, skin_max=1.0,
                rarity="Restricted", weapon="AWP", paint=None):
    return OutputSkin(
        base_name=base,
        weapon=weapon,
        paint=paint or base.split(" | ")[-1],
        rarity=rarity,
        collection=collection,
        skin_min=skin_min,
        skin_max=skin_max,
        variants=variants,
    )


def flat_proceeds(value):
    return lambda name: (value, "steam") if name else (None, None)


class TestWear:
    def test_bucket_boundaries(self):
        assert wear_bucket(0.00) == "Factory New"
        assert wear_bucket(0.069) == "Factory New"
        assert wear_bucket(0.07) == "Minimal Wear"
        assert wear_bucket(0.15) == "Field-Tested"
        assert wear_bucket(0.38) == "Well-Worn"
        assert wear_bucket(0.45) == "Battle-Scarred"
        assert wear_bucket(1.0) == "Battle-Scarred"

    def test_wear_ranges_intersection(self):
        ranges = list(wear_ranges(0.06, 0.80))
        wears = [w for w, _, _ in ranges]
        assert wears == ["Factory New", "Minimal Wear", "Field-Tested",
                         "Well-Worn", "Battle-Scarred"]
        fn = ranges[0]
        assert abs(fn[1] - 0.06) < 1e-9 and abs(fn[2] - 0.07) < 1e-9
        bs = ranges[-1]
        assert abs(bs[1] - 0.45) < 1e-9 and abs(bs[2] - 0.80) < 1e-9

    def test_wear_ranges_partial(self):
        wears = [w for w, _, _ in wear_ranges(0.20, 0.40)]
        assert wears == ["Field-Tested", "Well-Worn"]


class TestWearRatio:
    def test_known_float(self):
        i = make_input("a", "C", 1.0, skin_min=0.0, skin_max=1.0, float_value=0.25)
        assert abs(i.wear_ratio() - 0.25) < 1e-9

    def test_unknown_float_uses_wear_midpoint(self):
        i = make_input("a", "C", 1.0, skin_min=0.0, skin_max=1.0,
                       wear_min=0.15, wear_max=0.38)
        assert abs(i.wear_ratio() - 0.265) < 1e-9

    def test_clamps_out_of_range_float(self):
        i = make_input("a", "C", 1.0, skin_min=0.06, skin_max=0.80, float_value=0.99)
        assert abs(i.wear_ratio() - 1.0) < 1e-9


class TestEvaluateContract:
    def test_single_collection_ev(self):
        inputs = [make_input(f"i{n}", "Coll", 1.0) for n in range(CONTRACT_SIZE)]
        out = make_output(
            "AWP | Foo", "Coll",
            {"Field-Tested": "AWP | Foo (Field-Tested)"},
            skin_min=0.0, skin_max=1.0,
        )
        proceeds = flat_proceeds(50.0)
        result = evaluate_contract(inputs, {"Coll": [out]}, proceeds)
        assert result is not None
        assert abs(result["cost"] - 10.0) < 1e-9
        assert abs(result["ev_gross"] - 50.0) < 1e-9
        assert abs(result["ev_net"] - 40.0) < 1e-9
        assert abs(result["roi_pct"] - 400.0) < 1e-9
        assert result["distribution"][0]["prob"] == 1.0

    def test_mix_two_collections(self):
        inputs = [make_input("a", "A", 1.0) for _ in range(6)] + \
                 [make_input("b", "B", 2.0) for _ in range(4)]
        out_a = make_output("X | A", "A", {"Field-Tested": "X | A (Field-Tested)"})
        out_b = make_output("Y | B", "B", {"Field-Tested": "Y | B (Field-Tested)"})
        result = evaluate_contract(
            inputs, {"A": [out_a], "B": [out_b]}, flat_proceeds(100.0)
        )
        assert result is not None
        assert abs(result["cost"] - 14.0) < 1e-9
        probs = {d["base"]: d["prob"] for d in result["distribution"]}
        assert abs(probs["X | A"] - 0.6) < 1e-9
        assert abs(probs["Y | B"] - 0.4) < 1e-9
        assert abs(result["ev_gross"] - 100.0) < 1e-9

    def test_output_float_projection_selects_wear(self):
        hi = make_input("hi", "C", 1.0, skin_min=0.0, skin_max=1.0,
                        wear_min=0.0, wear_max=0.07, float_value=0.0)
        inputs = [hi] + [make_input(f"m{n}", "C", 1.0, wear_min=0.15,
                                    wear_max=0.38) for n in range(9)]
        out = make_output(
            "Z | C", "C",
            {"Factory New": "Z | C (Factory New)",
             "Minimal Wear": "Z | C (Minimal Wear)"},
            skin_min=0.0, skin_max=1.0,
        )
        result = evaluate_contract(inputs, {"C": [out]},
                                   lambda n: (10.0, "steam") if n else (None, None))
        top = result["distribution"][0]
        # ratios: 0.0 + 9×0.265 → avg = 0.2385 → float 0.2385 → Field-Tested…
        # mas o output só tem FN/MW → fallback para o melhor com preço (10.0)
        assert top["net"] == 10.0

    def test_wrong_size_returns_none(self):
        inputs = [make_input(f"i{n}", "C", 1.0) for n in range(9)]
        assert evaluate_contract(inputs, {}, flat_proceeds(1.0)) is None
