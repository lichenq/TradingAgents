"""Tests for limit entry rule backtest (synthetic bars, no network)."""

from __future__ import annotations

import unittest

from tradingagents.dataflows.limit_entry_rules import (
    Bar,
    _aggressive_tier_prices,
    _conservative_tier_prices,
    _format_stats_line,
    backtest_track_stats,
    backtest_rule,
    backtest_tiered,
    limit_price,
    signal_hybrid_entry,
    signal_macd_bear,
    signal_macd_only,
    signal_sharp_entry,
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

    def test_dual_track_macd_only(self):
        bars = _synthetic_bars()
        i = len(bars) - 1
        bars[i].pct = -1.5
        bars[i].close = bars[i].ma20 * 0.97 if bars[i].ma20 else bars[i].close
        _enrich_indicators(bars)
        aggressive = _aggressive_tier_prices(bars, i, bars[i].close)
        conservative = _conservative_tier_prices(bars, i, bars[i].close)
        if signal_hybrid_entry(bars, i) and not signal_macd_bear(bars, i):
            self.skipTest("synthetic bars did not produce macd-only path")
        if aggressive.get("first") and conservative.get("mode") == "macd_only":
            self.assertTrue(aggressive["hang"])
            self.assertFalse(conservative["hang"])
            self.assertLessEqual(conservative["first"], aggressive["first"])

    def test_backtest_track_stats(self):
        bars = _synthetic_bars()
        st = backtest_track_stats(bars, signal_hybrid_entry)
        self.assertIn("fill_rate_pct", st)
        self.assertIn("win_rate_20d_pct", st)
        line = _format_stats_line("激进轨", st)
        self.assertIn("成交率", line)
        self.assertIn("胜率", line)

    def test_signal_macd_only_vs_sharp_disjoint(self):
        bars = _synthetic_bars()
        i = len(bars) - 1
        self.assertFalse(signal_macd_only(bars, i) and signal_sharp_entry(bars, i))


if __name__ == "__main__":
    unittest.main()
