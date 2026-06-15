"""Tests for backtest audit context formatting."""

from __future__ import annotations

import tempfile
import unittest

from tradingagents.dataflows.backtest_audit_context import (
    audit_win_rate_summary,
    format_backtest_audit_context,
)
from tradingagents.graph.storage import init_db, save_backtest_audit


class TestBacktestAuditContext(unittest.TestCase):

    def test_format_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_db(tmp)
            save_backtest_audit(
                tmp,
                ticker="sz300604",
                recommendation_date="2026-05-27",
                audit_date="2026-05-30",
                days_elapsed=3,
                initial_price=229.19,
                end_price=240.0,
                raw_return=0.0471,
                reflection="Momentum held; tighten PE filter on hot names.",
            )
            save_backtest_audit(
                tmp,
                ticker="sz002484",
                recommendation_date="2026-06-10",
                audit_date="2026-06-13",
                days_elapsed=3,
                initial_price=80.0,
                end_price=76.0,
                raw_return=-0.05,
                reflection="High PE Hold was correct; avoid chase.",
            )
            ctx = format_backtest_audit_context(tmp, limit=5)
            self.assertIn("300604", ctx)
            self.assertIn("002484", ctx)
            self.assertIn("win_rate", ctx)
            stats = audit_win_rate_summary(tmp)
            self.assertEqual(stats["count"], 2)
            self.assertEqual(stats["win_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
