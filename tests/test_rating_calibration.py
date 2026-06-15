"""Tests for rating calibration."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date

from tradingagents.dataflows.rating_calibration import (
    build_rating_calibration,
    should_downgrade_buy,
)
from tradingagents.graph.storage import (
    init_db,
    save_backtest_audit,
    save_recommendation,
)


class TestRatingCalibration(unittest.TestCase):

    def test_downgrade_buy_on_negative_avg(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_db(tmp)
            for i, ret in enumerate([-0.05, -0.03, -0.02]):
                code = f"sz30{i:04d}"
                td = f"2026-06-{10 + i:02d}"
                save_recommendation(
                    tmp,
                    td,
                    "trend_pullback",
                    {
                        "code": code,
                        "name": "T",
                        "score": 80,
                        "price": 10,
                        "rating": "Buy",
                        "reason": "t",
                        "metrics": {},
                        "report_paths": {},
                    },
                )
                save_backtest_audit(
                    tmp,
                    ticker=code,
                    recommendation_date=td,
                    audit_date="2026-06-15",
                    days_elapsed=3,
                    initial_price=10,
                    end_price=10 * (1 + ret),
                    raw_return=ret,
                    reflection="x",
                )
            cal = build_rating_calibration(tmp, as_of=date(2026, 6, 15))
            self.assertTrue(cal["downgrade_buy"])
            self.assertTrue(should_downgrade_buy(tmp, as_of=date(2026, 6, 15)))


if __name__ == "__main__":
    unittest.main()
