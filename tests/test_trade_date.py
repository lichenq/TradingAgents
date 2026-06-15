"""Default trade_date resolution."""

import unittest
from datetime import date, datetime
from unittest.mock import patch

from tradingagents.dataflows.trade_date import (
    _cn_default_trade_date,
    _us_default_trade_date,
    cn_trading_sessions_after,
    resolve_default_trade_date,
)


class TestTradeDate(unittest.TestCase):
    def test_us_weekday_is_today(self):
        # 2026-05-22 is Friday
        self.assertEqual(
            _us_default_trade_date(date(2026, 5, 22)),
            "2026-05-22",
        )

    def test_us_saturday_uses_friday(self):
        self.assertEqual(
            _us_default_trade_date(date(2026, 5, 23)),
            "2026-05-22",
        )

    def test_cn_saturday_uses_friday(self):
        with patch(
            "tradingagents.dataflows.trade_date._cn_trading_days_between",
            return_value={"2026-05-20", "2026-05-21", "2026-05-22"},
        ):
            self.assertEqual(
                _cn_default_trade_date(date(2026, 5, 23)),
                "2026-05-22",
            )

    def test_cn_weekday_in_calendar(self):
        with patch(
            "tradingagents.dataflows.trade_date._cn_trading_days_between",
            return_value={"2026-05-22", "2026-05-23"},
        ):
            self.assertEqual(
                _cn_default_trade_date(date(2026, 5, 23)),
                "2026-05-23",
            )

    def test_resolve_cn_ticker(self):
        with patch(
            "tradingagents.dataflows.trade_date._cn_default_trade_date",
            return_value="2026-05-22",
        ) as mock_cn:
            out = resolve_default_trade_date(
                "688981.SS",
                {"market_profile": "cn"},
                as_of=datetime(2026, 5, 23, 12, 0, 0),
            )
            mock_cn.assert_called_once()
            self.assertEqual(out, "2026-05-22")

    def test_cn_trading_sessions_after(self):
        with patch(
            "tradingagents.dataflows.trade_date._cn_trading_days_between",
            return_value={"2026-06-10", "2026-06-11", "2026-06-12", "2026-06-15"},
        ):
            # Fri rec -> Mon as_of: sessions 6/11, 6/12, 6/15 = 3
            self.assertEqual(
                cn_trading_sessions_after("2026-06-10", date(2026, 6, 15)),
                3,
            )
            self.assertEqual(
                cn_trading_sessions_after("2026-06-12", date(2026, 6, 15)),
                1,
            )


if __name__ == "__main__":
    unittest.main()
