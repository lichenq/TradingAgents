"""Tests for recommendation loop health verification."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tradingagents.dataflows.recommendation_loop_health import run_health_checks
from tradingagents.graph.storage import (
    init_db,
    save_backtest_audit,
    save_recommendation,
)


class TestRecommendationLoopHealth(unittest.TestCase):

    def test_ok_with_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_db(tmp)
            for i in range(5):
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
                    end_price=11,
                    raw_return=0.1,
                    reflection="ok",
                )
            out_dir = Path(tmp) / "audit_reports"
            out_dir.mkdir(parents=True)
            (out_dir / "latest.json").write_text(
                json.dumps({"overall": {"count": 5, "win_rate": 1.0, "avg_return": 0.1}}),
                encoding="utf-8",
            )
            report = run_health_checks(tmp, as_of=date(2026, 6, 15))
            self.assertIn(report["exit_code"], (0, 1))
            self.assertFalse(report["status"] == "critical")

    def test_critical_missing_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_health_checks(tmp, as_of=date(2026, 6, 15))
            self.assertEqual(report["exit_code"], 2)
            self.assertEqual(report["status"], "critical")


if __name__ == "__main__":
    unittest.main()
