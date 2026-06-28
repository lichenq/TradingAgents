"""Tests for audit-driven Stage1 tuning."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date

from tradingagents.dataflows.audit_stage1_tune import compute_audit_stage1_tune
from tradingagents.graph.storage import init_db, save_backtest_audit, save_recommendation


class TestAuditStage1Tune(unittest.TestCase):

    def test_tightens_on_high_pe_loss_streak(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_db(tmp)
            for i in range(3):
                td = f"2026-06-{10 + i:02d}"
                save_recommendation(
                    tmp,
                    td,
                    "trend_pullback",
                    {
                        "code": f"sz30040{i}",
                        "name": "T",
                        "score": 88,
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
                    f"sz30040{i}",
                    td,
                    "2026-06-20",
                    3,
                    10.0,
                    9.0,
                    -0.06,
                    "loss",
                    failure_modes=["high_pe_loss"],
                )
            tune = compute_audit_stage1_tune(tmp, "trend_pullback")
            self.assertEqual(tune.max_pe_cap, 55.0)


if __name__ == "__main__":
    unittest.main()
