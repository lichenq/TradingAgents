"""Tests for CN technical indicator prefetch."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tradingagents.dataflows.cn_prefetch import clear_prefetch_cache, get_prefetched
from tradingagents.dataflows.cn_technical import (
    format_cn_technical_block,
    require_cn_technical_ready,
)


def _sample_rows() -> list:
    base = {
        "close": 65.0,
        "MA5": 66.0,
        "MA10": 67.0,
        "MA20": 68.0,
        "MA60": 70.0,
        "MACD_DIF": -0.5,
        "MACD_DEA": -0.3,
        "MACD": -0.4,
        "RSI": 42.0,
        "BOLL_UP": 70.0,
        "BOLL_MID": 66.0,
        "BOLL_LOW": 62.0,
    }
    prev = {**base, "time": "2026-07-02", "MACD_DIF": -0.8, "MACD_DEA": -0.4}
    last = {**base, "time": "2026-07-03", "MACD_DIF": -0.2, "MACD_DEA": -0.3}
    return [prev, last]


class TestCnTechnical(unittest.TestCase):

    def setUp(self):
        clear_prefetch_cache()

    def tearDown(self):
        clear_prefetch_cache()

    def test_format_block_contains_macd_and_rsi(self):
        block = format_cn_technical_block("601138", "2026-07-03", _sample_rows())
        self.assertIn("MACD_DIF", block)
        self.assertIn("RSI=", block)
        self.assertIn("601138", block)

    def test_require_raises_when_missing(self):
        with self.assertRaises(RuntimeError):
            require_cn_technical_ready("601138")

    @patch("tradingagents.dataflows.cn_technical.run_script")
    def test_fetch_and_cache_ok(self, mock_run):
        from tradingagents.dataflows.cn_technical import fetch_and_cache_cn_technical

        mock_run.return_value = (True, "", _sample_rows())
        status, ok = fetch_and_cache_cn_technical("601138", "2026-07-03")
        self.assertTrue(ok)
        self.assertIn("MACD_DIF", status)
        block = get_prefetched("technical:601138")
        self.assertIn("MACD 金叉", block or "")


if __name__ == "__main__":
    unittest.main()
