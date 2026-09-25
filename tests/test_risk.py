import os
import tempfile

import pytest

import db
from engine import risk


@pytest.fixture()
def conn():
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    db.init_db(path)
    with db.connect(path) as c:
        yield c


class TestStddev:
    def test_constant_series(self):
        assert risk.stddev([5.0, 5.0, 5.0]) == 0.0

    def test_known_values(self):
        assert risk.stddev([1.0, 2.0, 3.0, 4.0]) == pytest.approx(1.2909944, rel=1e-4)

    def test_too_few_points(self):
        assert risk.stddev([1.0]) == 0.0


class TestPriceStddev:
    def test_insufficient_history(self, conn):
        sd, n = risk.price_stddev(conn, "Ghost | Item", days=30)
        assert sd == 0.0 and n == 0

    def test_with_history(self, conn):
        for i in range(10):
            db.record_price(
                conn,
                market_hash_name="AK | T",
                source="steam",
                price=10.0 + (0.5 if i % 2 else -0.5),
                observed_at=f"2026-09-{i + 1:02d}T12:00:00.000000Z",
            )
        sd, n = risk.price_stddev(conn, "AK | T", days=90)
        assert n == 10
        assert sd == pytest.approx(0.5270, rel=1e-2)


class TestClassify:
    def test_robust(self):
        out = risk.classify(ev_net=10.0, risk_sd=3.0, multiplier=2.0, coverage=1.0)
        assert out["robust"] is True

    def test_not_robust_low_ev(self):
        out = risk.classify(ev_net=5.0, risk_sd=3.0, multiplier=2.0, coverage=1.0)
        assert out["robust"] is False

    def test_not_robust_insufficient_coverage(self):
        out = risk.classify(ev_net=100.0, risk_sd=0.1, multiplier=2.0, coverage=0.2)
        assert out["robust"] is False
        assert out["enough_data"] is False

    def test_negative_ev_never_robust(self):
        out = risk.classify(ev_net=-5.0, risk_sd=0.0, multiplier=2.0, coverage=1.0)
        assert out["robust"] is False
