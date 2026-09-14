"""Tests for audit failure-mode tagging."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from tradingagents.dataflows.audit_failure_modes import (
    classify_failure_modes,
    failure_mode_counts,
)
from tradingagents.graph.storage import init_db, save_backtest_audit, save_recommendation


class TestAuditFailureModes(unittest.TestCase):

    def test_high_pe_loss_on_actionable_drawdown(self):
        rec = {"rating": "Buy", "score": 70, "reason": "trend"}
        tags = classify_failure_modes(rec, -0.05, pe_ttm=80.0)
        self.assertIn("high_pe_loss", tags)

    def test_win_tag_on_positive_actionable(self):
        rec = {"rating": "Overweight", "score": 70, "reason": "trend"}
        tags = classify_failure_modes(rec, 0.06, pe_ttm=20.0)
        self.assertEqual(tags, ["win"])

    def test_failure_mode_counts_from_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_db(tmp)
            # Audit lookback windows are relative to today; use recent dates so
            # the fixtures stay inside them regardless of when the test runs.
            rec_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
            audit_date = (date.today() - timedelta(days=5)).strftime("%Y-%m-%d")
            save_recommendation(
                tmp,
                rec_date,
                "trend_pullback",
                {
                    "code": "sz000001",
                    "name": "Test",
                    "score": 90,
                    "price": 10.0,
                    "rating": "Buy",
                    "reason": "trend",
                    "metrics": {},
                    "report_paths": {},
                    "is_final": 1,
                },
            )
            save_backtest_audit(
                tmp,
                "sz000001",
                rec_date,
                audit_date,
                3,
                10.0,
                9.0,
                -0.10,
                "loss",
                failure_modes=["high_pe_loss"],
            )
            counts = failure_mode_counts(tmp, lookback_days=30)
            self.assertEqual(counts.get("high_pe_loss"), 1)


if __name__ == "__main__":
    unittest.main()
