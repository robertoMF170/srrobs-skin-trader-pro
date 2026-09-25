import os
import tempfile

import pytest

import db


@pytest.fixture()
def conn():
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    db.init_db(path)
    with db.connect(path) as c:
        yield c


class TestPrices:
    def test_record_and_latest(self, conn):
        db.record_price(conn, market_hash_name="A", source="steam", price=10.0)
        db.record_price(conn, market_hash_name="A", source="skinport", price=8.0)
        prices = db.latest_prices(conn, max_age_hours=1)
        assert prices["A"]["steam"]["price"] == 10.0
        assert prices["A"]["skinport"]["price"] == 8.0

    def test_latest_excludes_stale(self, conn):
        db.record_price(
            conn, market_hash_name="B", source="steam", price=5.0,
            observed_at="2020-01-01T00:00:00.000000Z",
        )
        assert "B" not in db.latest_prices(conn, max_age_hours=24)

    def test_currency_filter(self, conn):
        db.record_price(conn, market_hash_name="C", source="csfloat",
                        price=3.0, currency="USD")
        assert "C" not in db.latest_prices(conn, max_age_hours=24, currency="EUR")
        assert "C" in db.latest_prices(conn, max_age_hours=24, currency="USD")

    def test_series_window(self, conn):
        for day in range(1, 40):
            db.record_price(
                conn, market_hash_name="D", source="steam", price=1.0 * day,
                observed_at=f"2026-08-{day:02d}T00:00:00.000000Z",
            )
        series = db.price_series(conn, "D", days=5)
        assert len(series) == 0 or all(ts >= "2026-09-10" for ts, _ in series)


class TestOpportunities:
    def test_replace_and_list(self, conn):
        rows = [
            {"key": "k1", "ev_net": 10.0, "roi_pct": 20.0, "robust": True},
            {"key": "k2", "ev_net": 2.0, "roi_pct": 5.0, "robust": False},
        ]
        db.replace_opportunities(conn, "tradeup", rows)
        listed = db.list_opportunities(conn, "tradeup")
        assert [r["key"] for r in listed] == ["k1", "k2"]
        robust = db.list_opportunities(conn, "tradeup", robust_only=True)
        assert [r["key"] for r in robust] == ["k1"]
        db.replace_opportunities(conn, "tradeup", [{"key": "k3", "ev_net": 1.0,
                                                    "roi_pct": 1.0}])
        assert len(db.list_opportunities(conn, "tradeup")) == 1


class TestPositions:
    def test_lock_is_seven_days(self, conn):
        from datetime import datetime, timezone

        purchased = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        pos_id = db.add_position(
            conn, market_hash_name="X", source="steam",
            purchase_price=5.0, purchased_at=purchased,
        )
        row = conn.execute(
            "SELECT * FROM positions WHERE id=?", (pos_id,)
        ).fetchone()
        assert row["trade_lock_until"][:10] == "2026-01-08"
