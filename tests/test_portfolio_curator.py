"""Tests for Stage-3 portfolio curation (report loading + legacy filter)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tradingagents.graph.storage import init_db, save_report
from tradingagents.recommend.portfolio_curator import (
    _legacy_filter,
    curate_final_recommendations,
    resolve_complete_report_text,
)


class TestPortfolioCurator(unittest.TestCase):
    def test_legacy_filter_orders_by_rating_then_score(self):
        rows = [
            {"code": "sz000001", "rating": "Hold", "score": 10},
            {"code": "sz000002", "rating": "Buy", "score": 5},
            {"code": "sz000003", "rating": "Sell", "score": 99},
        ]
        out = _legacy_filter(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["rating"], "Buy")
        self.assertEqual(out[1]["rating"], "Hold")

    def test_resolve_complete_report_from_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp)
            init_db(results_dir)
            save_report(
                results_dir,
                ticker="sh688008",
                trade_date="2026-06-01",
                rating="Buy",
                complete_report="X" * 250,
                final_trade_decision="**Rating**: Buy\n\nEnough text.",
                investment_plan="plan",
            )
            item = {"code": "688008", "final_state": {}}
            text = resolve_complete_report_text(item, str(results_dir), "2026-06-01")
            self.assertGreaterEqual(len(text), 250)

    def test_skip_curation_uses_legacy(self):
        validated = [
            {"code": "sz688008", "rating": "Overweight", "score": 20},
            {"code": "sz000021", "rating": "Sell", "score": 30},
        ]
        selected, meta = curate_final_recommendations(
            validated,
            {"results_dir": "/tmp"},
            "2026-06-01",
            skip=True,
        )
        self.assertTrue(meta["skipped"])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["code"], "sz688008")


if __name__ == "__main__":
    unittest.main()
