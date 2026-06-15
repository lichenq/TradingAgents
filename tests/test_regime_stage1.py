"""Tests for regime-based Stage1 overrides."""

from __future__ import annotations

import unittest

from tradingagents.recommend.regime_stage1 import regime_stage1_params


class TestRegimeStage1(unittest.TestCase):

    def test_defensive_blocks_momentum(self):
        p = regime_stage1_params("DEFENSIVE_REGIME")
        self.assertIn("em_hot_momentum", p.blocked_strategies)
        self.assertEqual(p.validate_top_cap, 3)

    def test_high_heat_default(self):
        p = regime_stage1_params("HIGH_HEAT_REGIME")
        self.assertEqual(len(p.blocked_strategies), 0)


if __name__ == "__main__":
    unittest.main()
