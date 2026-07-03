"""Tests for Tuige rebalance + regime detection."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tradingagents.tuige.context import build_tuige_context
from tradingagents.tuige.rebalance_detector import detect_rebalance_window
from tradingagents.tuige.regime import apply_rebalance_modifier, detect_base_regime
from tradingagents.tuige.snapshot import MarketSnapshot, snapshot_from_quotes
from tradingagents.tuige.stage1_advisory import stage1_advisory_for_regime
from tradingagents.recommend.regime_stage1 import regime_stage1_params


def _jul1_quotes(n_up: int = 4000) -> list:
    rows = [{"code": f"{i:06d}", "change_pct": 1.0, "amount": 1e9} for i in range(n_up)]
    rows.extend([
        {"code": "000001", "change_pct": 0.44, "amount": 0},
        {"code": "399006", "change_pct": -0.93, "amount": 0},
        {"code": "000688", "change_pct": -1.27, "amount": 0},
    ])
    return rows


class TestTuigeRebalance(unittest.TestCase):

    def test_jul1_like_rebalance_yes(self):
        flows = [
            {"name": "半导体", "main_net_inflow_yuan": -2.4e10},
            {"name": "通信设备", "main_net_inflow_yuan": -2.1e10},
            {"name": "证券", "main_net_inflow_yuan": 8.9e9},
            {"name": "保险", "main_net_inflow_yuan": 1.4e9},
        ]
        snap = snapshot_from_quotes(
            "2026-07-01",
            _jul1_quotes(),
            industry_flows=flows,
        )
        snap.total_amount_yuan = 3.7e12
        snap.index_changes = {"shanghai": 0.44, "chinext": -0.93, "star50": -1.27}
        reb = detect_rebalance_window(snap)
        self.assertIn(reb.window, ("yes", "watch"))
        self.assertGreaterEqual(len(reb.signal_hits), 2)

    def test_aggressive_downgraded_on_rebalance(self):
        snap = MarketSnapshot(trade_date="2026-07-01")
        base, _ = detect_base_regime(snap)
        from tradingagents.tuige.rebalance_detector import RebalanceAssessment

        effective = apply_rebalance_modifier(
            "aggressive",
            RebalanceAssessment(window="yes", signal_hits=["a", "b", "c"]),
        )
        self.assertEqual(effective, "rotation")

    def test_rotation_blocks_momentum_advisory(self):
        p = regime_stage1_params("rotation", rebalance_window="yes")
        self.assertIn("em_hot_momentum", p.blocked_strategies)
        self.assertEqual(p.validate_top_cap, 3)

    @patch("tradingagents.tuige.context.get_config")
    def test_build_context_dict(self, mock_cfg):
        mock_cfg.return_value = {"market_profile": "cn", "tuige_enabled": True, "tuige_strict": False, "position_context_regime": "auto"}
        ctx = build_tuige_context(
            "2026-07-01",
            quotes=_jul1_quotes(),
            industry_flows=[
                {"name": "半导体", "main_net_inflow_yuan": -2e10},
                {"name": "证券", "main_net_inflow_yuan": 9e9},
            ],
        )
        d = ctx.to_dict()
        self.assertTrue(d["enabled"])
        self.assertIn("effective_regime", d)
        self.assertIn("rebalance_window", d)


if __name__ == "__main__":
    unittest.main()
