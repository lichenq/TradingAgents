"""Tests for Tuige market input cache and index payload normalization."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tradingagents.tuige.market_inputs import (
    TuigeMarketInputs,
    clear_tuige_market_cache,
    fetch_tuige_market_inputs,
    normalize_index_payload,
)


class TestTuigeMarketInputs(unittest.TestCase):

    def setUp(self):
        clear_tuige_market_cache()

    def tearDown(self):
        clear_tuige_market_cache()

    def test_normalize_index_list(self):
        payload = normalize_index_payload([{"代码": "sh000001", "涨跌幅(%)": 0.5}])
        self.assertEqual(payload, {"data": [{"代码": "sh000001", "涨跌幅(%)": 0.5}]})

    @patch("tradingagents.tuige.market_inputs._fetch_index_and_flows")
    def test_reuse_external_quotes_skips_all_quote(self, mock_fetch):
        mock_fetch.return_value = TuigeMarketInputs(
            index_payload={"data": [{"代码": "sh000001", "涨跌幅(%)": 0.5}]},
            industry_flows=[{"name": "半导体", "main_net_inflow_yuan": -1e9}],
        )
        quotes = [{"code": "600000", "change_pct": 1.0, "amount": 1e9}]

        first = fetch_tuige_market_inputs("2026-07-03", quotes=quotes)
        second = fetch_tuige_market_inputs("2026-07-03", quotes=quotes)

        self.assertEqual(first.quotes, quotes)
        self.assertEqual(second.quotes, quotes)
        self.assertIsNotNone(first.index_payload)
        mock_fetch.assert_called_once()

    @patch("tradingagents.tuige.market_inputs._fetch_all_quotes")
    @patch("tradingagents.tuige.market_inputs._fetch_industry_flows")
    @patch("tradingagents.tuige.market_inputs._fetch_index")
    def test_full_fetch_cached(self, mock_index, mock_flow, mock_quotes):
        mock_index.return_value = {"data": [{"代码": "sh000001", "涨跌幅(%)": 0.5}]}
        mock_flow.return_value = [{"name": "证券", "main_net_inflow_yuan": 1e9}]
        mock_quotes.return_value = [{"code": "600000", "change_pct": 1.0, "amount": 1e9}]

        fetch_tuige_market_inputs("2026-07-03")
        fetch_tuige_market_inputs("2026-07-03")

        mock_index.assert_called_once()
        mock_flow.assert_called_once()
        mock_quotes.assert_called_once()


if __name__ == "__main__":
    unittest.main()
