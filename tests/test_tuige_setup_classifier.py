"""Tests for Tuige setup classifier (Phase 2)."""

from __future__ import annotations

import unittest

import pandas as pd

from tradingagents.tuige.setup_classifier import classify_setup
from tradingagents.tuige.stage3_gates import derive_position_grade, evaluate_tuige_setup_gate


def _base_df(n: int = 80) -> pd.DataFrame:
    rows = []
    price = 10.0
    for i in range(n):
        rows.append(
            {
                "time": f"2026-01-{i+1:02d}",
                "open": price,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": 1_000_000 + i * 1000,
            }
        )
        price += 0.02
    return pd.DataFrame(rows)


class TestSetupClassifier(unittest.TestCase):

    def test_trend_pullback_setup(self):
        df = _base_df(60)
        df["MA10"] = df["close"].rolling(10).mean()
        df["MA30"] = df["close"].rolling(30).mean()
        df.loc[df.index[-1], "close"] = float(df.iloc[-1]["MA10"]) * 1.005
        cls = classify_setup(df, code6="600000", strategy_hint="trend_pullback")
        self.assertEqual(cls.setup, "trend-setups")

    def test_relay_two_limit_ups(self):
        df = _base_df(40)
        df.loc[df.index[-2], "close"] = df.iloc[-3]["close"] * 1.1
        df.loc[df.index[-1], "close"] = df.iloc[-2]["close"] * 1.1
        cls = classify_setup(df, code6="600000")
        self.assertEqual(cls.setup, "relay-setups")
        self.assertGreaterEqual(cls.confidence, 0.85)

    def test_limit_up_pullback(self):
        df = _base_df(50)
        base = float(df.iloc[-8]["close"])
        df.loc[df.index[-8], "close"] = base * 1.1
        df.loc[df.index[-8], "low"] = base
        df.loc[df.index[-8], "high"] = base * 1.1
        for idx in df.index[-7:]:
            df.loc[idx, "close"] = base * 1.04
            df.loc[idx, "volume"] = 500_000
        cls = classify_setup(df, code6="600000")
        self.assertEqual(cls.setup, "limit-up-pullback-setups")


class TestStage3Gates(unittest.TestCase):

    def test_relay_blocked_on_rebalance(self):
        ctx = {
            "enabled": True,
            "effective_regime": "rotation",
            "rebalance_window": "yes",
            "allowed_setups": ["trend-setups"],
            "blocked_setups": ["relay-setups"],
        }
        item = {"tuige_setup": "relay-setups", "rating": "Buy"}
        ok, reason = evaluate_tuige_setup_gate(item, ctx, strict=False)
        self.assertFalse(ok)
        self.assertIn("换仓", reason)

    def test_trend_allowed_on_rebalance(self):
        ctx = {
            "enabled": True,
            "rebalance_window": "yes",
            "allowed_setups": ["trend-setups"],
            "blocked_setups": ["relay-setups"],
        }
        item = {"tuige_setup": "trend-setups", "rating": "Buy"}
        ok, _ = evaluate_tuige_setup_gate(item, ctx, strict=False)
        self.assertTrue(ok)

    def test_position_grade_relay_light(self):
        ctx = {"enabled": True, "effective_regime": "aggressive", "rebalance_window": "no"}
        grade = derive_position_grade(ctx, "relay-setups")
        self.assertEqual(grade, "light")


if __name__ == "__main__":
    unittest.main()
