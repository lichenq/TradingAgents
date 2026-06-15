"""Tests for P1 audit feedback hard gates."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from tradingagents.dataflows.audit_feedback_gates import (
    build_cautious_sectors,
    evaluate_sector_high_pe_gate,
    evaluate_strategy_audit_gate,
)
from tradingagents.graph.storage import (
    init_db,
    save_backtest_audit,
    save_recommendation,
)


class TestAuditFeedbackGates(unittest.TestCase):

    def _seed_strategy_audits(self, tmp: str, strategy: str, returns: list[float]) -> None:
        init_db(tmp)
        for i, ret in enumerate(returns):
            code = f"sz30{i:04d}"
            td = f"2026-06-{10 + i:02d}"
            save_recommendation(
                tmp,
                td,
                strategy,
                {
                    "code": code,
                    "name": f"Test{i}",
                    "score": 80.0,
                    "price": 10.0,
                    "rating": "Buy",
                    "reason": "test",
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
                initial_price=10.0,
                end_price=10.0 * (1 + ret),
                raw_return=ret,
                reflection="test",
            )

    def test_strategy_gate_blocks_low_win_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._seed_strategy_audits(
                tmp, "em_hot_momentum", [-0.05, -0.03, -0.02, -0.01, -0.04, -0.02]
            )
            gate = evaluate_strategy_audit_gate(
                tmp, "em_hot_momentum", as_of=date(2026, 6, 15)
            )
            self.assertFalse(gate["allowed"])
            self.assertIn("OOS", gate["reason"])

    def test_strategy_gate_allows_good_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._seed_strategy_audits(
                tmp, "trend_pullback", [0.1, 0.12, 0.08]
            )
            gate = evaluate_strategy_audit_gate(
                tmp, "trend_pullback", as_of=date(2026, 6, 15)
            )
            self.assertTrue(gate["allowed"])

    def test_strategy_gate_insufficient_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._seed_strategy_audits(tmp, "trend_pullback", [-0.1])
            gate = evaluate_strategy_audit_gate(
                tmp, "trend_pullback", as_of=date(2026, 6, 15)
            )
            self.assertTrue(gate["allowed"])
            self.assertIn("samples", gate["reason"])

    def test_cautious_sectors_from_bearish_losses(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_db(tmp)
            save_recommendation(
                tmp,
                "2026-06-10",
                "trend_pullback",
                {
                    "code": "sz002484",
                    "name": "江海股份",
                    "score": 70.0,
                    "price": 80.0,
                    "rating": "Hold",
                    "reason": "high pe",
                    "metrics": {},
                    "report_paths": {},
                },
            )
            save_recommendation(
                tmp,
                "2026-06-11",
                "trend_pullback",
                {
                    "code": "sz300408",
                    "name": "三环集团",
                    "score": 65.0,
                    "price": 40.0,
                    "rating": "Underweight",
                    "reason": "high pe",
                    "metrics": {},
                    "report_paths": {},
                },
            )
            for code, td in (("sz002484", "2026-06-10"), ("sz300408", "2026-06-11")):
                save_backtest_audit(
                    tmp,
                    ticker=code,
                    recommendation_date=td,
                    audit_date="2026-06-15",
                    days_elapsed=3,
                    initial_price=80.0,
                    end_price=70.0,
                    raw_return=-0.1,
                    reflection="bearish ok",
                )

            with patch(
                "tradingagents.dataflows.audit_feedback_gates._canonical_industry_for_ticker",
                return_value="元件",
            ):
                cautious = build_cautious_sectors(tmp, as_of=date(2026, 6, 15))

            self.assertIn("元件", cautious)
            self.assertGreaterEqual(cautious["元件"]["loss_count"], 2)

    def test_sector_high_pe_prune(self):
        cautious = {"元件": {"loss_count": 2, "tickers": ["002484"]}}
        with patch(
            "tradingagents.dataflows.audit_feedback_gates._canonical_industry_for_ticker",
            return_value="元件",
        ), patch(
            "tradingagents.dataflows.cn_valuation.fetch_cn_valuation_payload",
            return_value=(True, {"pe_ttm": 107.0}, ""),
        ):
            flagged, reason = evaluate_sector_high_pe_gate(
                "sz002484",
                "2026-06-15",
                cautious,
                {},
            )
        self.assertTrue(flagged)
        self.assertIn("元件", reason)
        self.assertIn("107", reason)


if __name__ == "__main__":
    unittest.main()
