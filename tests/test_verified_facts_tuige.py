"""Tests for Tuige prompt injection with setup block."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tradingagents.agents.utils.verified_facts import append_verified_market_facts


class TestVerifiedFactsTuigeSetup(unittest.TestCase):

    @patch("tradingagents.agents.utils.verified_facts.tuige_enabled", return_value=True)
    @patch("tradingagents.agents.utils.verified_facts.build_tuige_context")
    @patch("tradingagents.agents.utils.verified_facts.detect_market_regime", return_value="rotation")
    @patch("tradingagents.agents.utils.verified_facts.get_regime_prompt_instructions", return_value="REGIME")
    def test_setup_block_injected(self, _regime_prompt, _detect, mock_ctx, _enabled):
        mock_ctx.return_value.enabled = True
        mock_ctx.return_value.base_regime = "rotation"
        mock_ctx.return_value.effective_regime = "rotation"
        mock_ctx.return_value.rebalance_window = "no"
        mock_ctx.return_value.signal_hits = []
        mock_ctx.return_value.allowed_setups = ["trend-setups"]
        mock_ctx.return_value.blocked_setups = []
        mock_ctx.return_value.position_cap = "light"
        mock_ctx.return_value.rebalance_note = ""
        mock_ctx.return_value.reminders = []
        mock_ctx.return_value.tuige_setup = "trend-setups"
        mock_ctx.return_value.tuige_setup_rationale = ""

        state = {
            "verified_market_facts": "PE: 20x",
            "company_of_interest": "600000",
            "trade_date": "2026-07-01",
            "tuige_setup": "trend-setups",
        }
        out = append_verified_market_facts("BASE", state)
        self.assertIn("trend-setups", out)
        self.assertIn("Tuige 个股场景", out)


if __name__ == "__main__":
    unittest.main()
