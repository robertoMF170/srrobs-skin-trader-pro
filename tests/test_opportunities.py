from engine.opportunities import compute_resale, make_proceeds, sale_net


class TestSaleNet:
    def test_steam_fee(self):
        assert sale_net("steam", 100.0) == 85.0

    def test_steam_ref_same_fee(self):
        assert sale_net("steam_ref", 100.0) == 85.0

    def test_third_party_fee(self):
        assert sale_net("skinport", 100.0) == 95.0


class TestProceeds:
    def test_prefers_real_steam(self):
        prices = {
            "X": {
                "steam": {"price": 10.0},
                "steam_ref": {"price": 20.0},
                "skinport": {"price": 8.0},
            }
        }
        net, src = make_proceeds(prices)("X")
        assert (net, src) == (8.5, "steam")

    def test_falls_back_to_steam_ref(self):
        prices = {"X": {"steam_ref": {"price": 20.0}, "skinport": {"price": 8.0}}}
        net, src = make_proceeds(prices)("X")
        assert (net, src) == (17.0, "steam_ref")

    def test_falls_back_to_third_party(self):
        prices = {"X": {"skinport": {"price": 8.0}, "csfloat": {"price": 12.0}}}
        net, src = make_proceeds(prices)("X")
        assert (net, src) == (11.4, "csfloat")


class TestComputeResale:
    def test_any_two_sources(self):
        prices = {
            "A | B (FT)": {
                "skinport": {"price": 7.0},
                "steam_ref": {"price": 12.0},
            }
        }
        rows = compute_resale(prices)
        assert len(rows) == 1
        r = rows[0]
        assert r["buy_source"] == "skinport"
        assert r["buy_price"] == 7.0
        assert r["sell_source"] == "steam_ref"
        assert r["sell_net"] == 10.2
        assert r["ev_net"] == 3.2
        assert abs(r["roi_pct"] - 45.71) < 0.01

    def test_single_source_skipped(self):
        assert compute_resale({"A": {"skinport": {"price": 5.0}}}) == []

    def test_steam_is_never_a_buy_source(self):
        prices = {
            "A | B (FT)": {
                "steam": {"price": 4.0},
                "skinport": {"price": 7.0},
                "steam_ref": {"price": 12.0},
            }
        }
        rows = compute_resale(prices)
        assert len(rows) == 1
        r = rows[0]
        assert r["buy_source"] == "skinport"
        assert r["buy_price"] == 7.0
        # vende na mais valiosa: steam 4.0*0.85=3.4 vs steam_ref 12*0.85=10.2
        assert r["sell_source"] == "steam_ref"

    def test_steam_ref_is_never_a_buy_source(self):
        prices = {
            "? Bayonet | Fake (Battle-Scarred)": {
                "steam_ref": {"price": 137.0},
                "skinport": {"price": 5225.0},
            }
        }
        rows = compute_resale(prices)
        assert len(rows) == 1
        r = rows[0]
        assert r["buy_source"] == "skinport"
        assert r["buy_price"] == 5225.0
        assert r["sell_source"] == "steam_ref"
        assert r["ev_net"] < 0

    def test_does_not_buy_and_sell_same_source(self):
        prices = {
            "A": {
                "skinport": {"price": 5.0},
                "csfloat": {"price": 6.0},
            }
        }
        rows = compute_resale(prices)
        assert rows[0]["buy_source"] == "skinport"
        assert rows[0]["sell_source"] == "csfloat"
        # 6.0*0.95 - 5.0 = 0.7
        assert abs(rows[0]["ev_net"] - 0.7) < 1e-9
