"""CN OHLCV end-date resolution for live vs backtest runs."""

import unittest
from datetime import datetime

from tradingagents.dataflows.cn_market_dates import cn_ohlcv_end_date, is_live_analysis


class TestCnMarketDates(unittest.TestCase):
    def test_live_run_extends_to_today(self):
        end = cn_ohlcv_end_date("2026-05-23", now=datetime(2026, 5, 25, 10, 0, 0))
        self.assertEqual(end, "2026-05-25")

    def test_backtest_keeps_trade_date(self):
        end = cn_ohlcv_end_date("2024-01-15", now=datetime(2026, 5, 25, 10, 0, 0))
        self.assertEqual(end, "2024-01-15")

    def test_future_trade_date_uses_today(self):
        end = cn_ohlcv_end_date("2026-12-31", now=datetime(2026, 5, 25, 10, 0, 0))
        self.assertEqual(end, "2026-05-25")

    def test_is_live_within_week(self):
        self.assertTrue(
            is_live_analysis("2026-05-23", now=datetime(2026, 5, 25, 10, 0, 0))
        )


if __name__ == "__main__":
    unittest.main()
