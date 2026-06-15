"""Tests for audit KPI report aggregation."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tradingagents.dataflows.audit_report import build_audit_report, write_audit_report
from tradingagents.graph.storage import (
    init_db,
    save_backtest_audit,
    save_recommendation,
)


class TestAuditReport(unittest.TestCase):

    def test_build_and_write_by_strategy_rating(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_db(tmp)
            save_recommendation(
                tmp,
                "2026-06-10",
                "trend_pullback",
                {
                    "code": "sz300408",
                    "name": "三环集团",
                    "score": 80.0,
                    "price": 40.0,
                    "rating": "Buy",
                    "reason": "trend",
                    "metrics": {},
                    "report_paths": {},
                },
            )
            save_recommendation(
                tmp,
                "2026-06-10",
                "em_hot_momentum",
                {
                    "code": "sz002484",
                    "name": "江海股份",
                    "score": 70.0,
                    "price": 80.0,
                    "rating": "Hold",
                    "reason": "hot",
                    "metrics": {},
                    "report_paths": {},
                },
            )
            save_backtest_audit(
                tmp,
                ticker="sz300408",
                recommendation_date="2026-06-10",
                audit_date="2026-06-15",
                days_elapsed=3,
                initial_price=40.0,
                end_price=48.0,
                raw_return=0.2,
                reflection="Buy worked.",
            )
            save_backtest_audit(
                tmp,
                ticker="sz002484",
                recommendation_date="2026-06-10",
                audit_date="2026-06-15",
                days_elapsed=3,
                initial_price=80.0,
                end_price=76.0,
                raw_return=-0.05,
                reflection="Hold was right.",
            )

            report = build_audit_report(tmp, lookback_days=30, as_of=date(2026, 6, 15))
            self.assertEqual(report["overall"]["count"], 2)
            self.assertEqual(report["overall"]["win_rate"], 0.5)
            self.assertIn("trend_pullback", report["by_strategy"])
            self.assertIn("Buy", report["by_rating"])
            self.assertIn("Hold", report["by_rating"])
            self.assertEqual(report["by_strategy"]["trend_pullback"]["win_rate"], 1.0)
            self.assertEqual(report["by_rating"]["Hold"]["win_rate"], 0.0)

            out = write_audit_report(tmp, lookback_days=30, as_of=date(2026, 6, 15))
            self.assertTrue(out.is_file())
            latest = Path(tmp) / "audit_reports" / "latest.json"
            self.assertTrue(latest.is_file())
            loaded = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(loaded["overall"]["count"], 2)


if __name__ == "__main__":
    unittest.main()
