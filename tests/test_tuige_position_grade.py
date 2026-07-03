"""Tests for Tuige position_grade enrichment (Phase 3)."""

from __future__ import annotations

import unittest

from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating, render_pm_decision
from tradingagents.tuige.position_grade import (
    derive_position_grade,
    enrich_final_trade_decision,
    format_position_grade_mandate,
)


class TestPositionGrade(unittest.TestCase):

    def test_derive_relay_no_trade_on_rebalance(self):
        ctx = {
            "enabled": True,
            "effective_regime": "rotation",
            "rebalance_window": "yes",
        }
        grade = derive_position_grade(ctx, "relay-setups")
        self.assertEqual(grade, "no_trade")

    def test_enrich_appends_grade_block(self):
        raw = "**Rating**: Hold\n\n**Executive Summary**: wait"
        out = enrich_final_trade_decision(
            raw,
            position_grade="light",
            tuige_setup="trend-setups",
            tuige_summary="环境=rotation | 换仓=no",
        )
        self.assertIn("**Position Grade**: light", out)
        self.assertIn("**Tuige Setup**: trend-setups", out)
        self.assertIn("Tuige Context", out)

    def test_render_pm_includes_grade(self):
        md = render_pm_decision(
            PortfolioDecision(
                rating=PortfolioRating.OVERWEIGHT,
                executive_summary="试探建仓",
                investment_thesis="趋势完好",
                position_grade="light",
                tuige_setup="trend-setups",
            )
        )
        self.assertIn("**Position Grade**: light", md)
        self.assertIn("**Tuige Setup**: trend-setups", md)

    def test_mandate_mentions_grade(self):
        block = format_position_grade_mandate("defensive", "washout-breakout-setups")
        self.assertIn("defensive", block)
        self.assertIn("washout-breakout-setups", block)


if __name__ == "__main__":
    unittest.main()
