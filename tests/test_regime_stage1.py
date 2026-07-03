"""Tests for regime-based Stage1 overrides (Tuige five-tier)."""

from __future__ import annotations

import unittest

from tradingagents.recommend.regime_stage1 import regime_stage1_params


class TestRegimeStage1(unittest.TestCase):

    def test_defensive_blocks_momentum(self):
        p = regime_stage1_params("defensive")
        self.assertIn("em_hot_momentum", p.blocked_strategies)
        self.assertEqual(p.validate_top_cap, 3)

    def test_aggressive_default(self):
        p = regime_stage1_params("aggressive")
        self.assertEqual(len(p.blocked_strategies), 0)

    def test_no_trade_blocks_all(self):
        p = regime_stage1_params("no_trade")
        self.assertIn("trend_pullback", p.blocked_strategies)


if __name__ == "__main__":
    unittest.main()
