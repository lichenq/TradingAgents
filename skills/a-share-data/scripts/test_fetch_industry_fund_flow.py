#!/usr/bin/env python3
"""Tests for fetch_industry_fund_flow.py."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import fetch_industry_fund_flow as mod


class TestIndustryFundFlow(unittest.TestCase):

    def test_parse_em_item(self):
        row = mod._parse_em_item({"f14": "半导体", "f62": 15401074688, "f3": 4.13})
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["industry"], "半导体")
        self.assertAlmostEqual(row["main_net_inflow_yi"], 154.01074688, places=4)
        self.assertEqual(row["change_pct"], 4.13)

    @patch("fetch_industry_fund_flow.fetch_ths_industry_rows")
    @patch("fetch_industry_fund_flow.fetch_em_industry_rows")
    def test_auto_falls_back_to_ths(self, mock_em, mock_ths):
        mock_em.side_effect = RuntimeError("em down")
        mock_ths.return_value = [{"industry": "电池", "main_net_inflow_yuan": 1.0, "main_net_inflow_yi": 1e-8, "change_pct": 1.0, "rank": 1}]
        with patch.dict(os.environ, {"A_SHARE_INDUSTRY_FUND_FLOW_SOURCE": "auto"}):
            items, source = mod.fetch_industry_rows(limit=1)
        self.assertEqual(source, "ths")
        self.assertEqual(items[0]["industry"], "电池")

    @patch("fetch_industry_fund_flow._fetch_em_page")
    def test_em_limit_uses_single_page(self, mock_page):
        mock_page.return_value = (
            [
                {"f14": "半导体", "f62": 20000000000, "f3": 3.0},
                {"f14": "银行", "f62": -1000000000, "f3": -1.0},
            ],
            496,
        )
        items = mod.fetch_em_industry_rows(limit=1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["industry"], "半导体")
        mock_page.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
