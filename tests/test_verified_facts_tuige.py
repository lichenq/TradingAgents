"""Tests for Tuige prompt injection with setup block."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tradingagents.agents.utils.verified_facts import append_verified_market_facts, resolve_tuige_context
from tradingagents.tuige.context import TuigeContext


class TestVerifiedFactsTuigeSetup(unittest.TestCase):

    @patch("tradingagents.agents.utils.verified_facts.tuige_enabled", return_value=True)
    def test_setup_block_injected(self, _enabled):
        ctx_dict = TuigeContext(
            enabled=True,
            effective_regime="rotation",
            allowed_setups=["trend-setups"],
            tuige_setup="trend-setups",
        ).to_dict()
        state = {
            "verified_market_facts": "PE: 20x",
            "company_of_interest": "600000",
            "trade_date": "2026-07-01",
            "tuige_setup": "trend-setups",
            "tuige_context": ctx_dict,
        }
        out = append_verified_market_facts("BASE", state)
        self.assertIn("trend-setups", out)
        self.assertIn("Tuige 个股场景", out)
        self.assertIn("rotation", out)

    @patch("tradingagents.agents.utils.verified_facts.tuige_enabled", return_value=True)
    def test_cached_tuige_context_used(self, _enabled):
        ctx_dict = TuigeContext(
            enabled=True,
            effective_regime="rotation",
            allowed_setups=["trend-setups"],
        ).to_dict()
        state = {
            "verified_market_facts": "PE: 20x",
            "tuige_context": ctx_dict,
        }
        ctx = resolve_tuige_context(state)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.effective_regime, "rotation")

    @patch("tradingagents.agents.utils.verified_facts.tuige_enabled", return_value=True)
    @patch("tradingagents.agents.utils.verified_facts.build_tuige_context")
    @patch("tradingagents.tuige.market_inputs.fetch_tuige_market_inputs")
    def test_fallback_builds_with_market_inputs(self, mock_fetch, mock_build, _enabled):
        mock_fetch.return_value.quotes = [{"code": "600000"}]
        mock_fetch.return_value.index_payload = {"data": []}
        mock_fetch.return_value.industry_flows = []
        mock_build.return_value = TuigeContext(enabled=True, effective_regime="defensive")

        state = {
            "verified_market_facts": "PE: 20x",
            "trade_date": "2026-07-01",
            "company_of_interest": "600000",
        }
        ctx = resolve_tuige_context(state)
        self.assertEqual(ctx.effective_regime, "defensive")
        mock_fetch.assert_called_once()
        mock_build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
