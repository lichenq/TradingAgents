"""Tests for limit entry rule backtest (synthetic bars, no network)."""

from __future__ import annotations

import unittest

from tradingagents.dataflows.limit_entry_rules import (
    Bar,
    backtest_rule,
    backtest_tiered,
    limit_price,
    signal_hybrid_entry,
    signal_macd_bear,
    summarize_stats,
    _enrich_indicators,
)


def _synthetic_bars(n: int = 80) -> list:
    bars = []
    price = 80.0
    for i in range(n):
        drift = -0.4 if i > 40 else 0.1
        low = price - 1.5
        high = price + 0.8
        close = price + drift
        bars.append(
            Bar(
                date=f"2026-01-{i+1:02d}" if i < 31 else f"2026-02-{i-30:02d}",
                open=price,
                high=high,
                low=low,
                close=close,
                pct=-2.0 if drift < 0 else 0.5,
            )
        )
        price = close
    _enrich_indicators(bars)
    return bars


class TestLimitEntryRules(unittest.TestCase):

    def test_hybrid_limit_below_close(self):
        bars = _synthetic_bars()
        i = len(bars) - 1
        lp = limit_price("hybrid", bars, i)
        self.assertIsNotNone(lp)
        self.assertLess(lp, bars[i].close)

    def test_backtest_produces_stats(self):
        bars = _synthetic_bars()
        st = backtest_rule(bars, "pct_5", signal_macd_bear)
        summary = summarize_stats(st)
        self.assertIn("fill_rate_pct", summary)
        self.assertIn("rule", summary)

    def test_signal_hybrid_entry(self):
        bars = _synthetic_bars()
        i = len(bars) - 1
        self.assertIsInstance(signal_hybrid_entry(bars, i), bool)

    def test_tiered_backtest_runs(self):
        bars = _synthetic_bars()
        st = backtest_tiered(bars, signal_macd_bear, fill_days=5)
        summary = summarize_stats(st)
        self.assertIn("win_rate_20d_pct", summary)


if __name__ == "__main__":
    unittest.main()
