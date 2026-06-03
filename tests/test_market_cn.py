"""Tests for China A-share market profile and ticker helpers."""

import unittest

from tradingagents.default_config import (
    CN_GLOBAL_NEWS_QUERIES,
    apply_market_profile,
)
from tradingagents.dataflows.sector_queries import (
    industry_to_search_queries,
    merge_news_queries,
    resolve_ticker_news_queries,
)
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.market import (
    cn_uses_a_share_skill,
    effective_market_profile,
    is_cn_ticker,
    normalize_a_share_code,
    to_yahoo_a_share_symbol,
)


class TestMarketDetection(unittest.TestCase):
    def test_is_cn_ticker_suffixes(self):
        self.assertTrue(is_cn_ticker("600519.SS"))
        self.assertTrue(is_cn_ticker("000001.SZ"))
        self.assertTrue(is_cn_ticker("600519"))

    def test_is_cn_ticker_us(self):
        self.assertFalse(is_cn_ticker("AAPL"))
        self.assertFalse(is_cn_ticker("NVDA"))

    def test_normalize_code(self):
        self.assertEqual(normalize_a_share_code("600519.SS"), "600519")
        self.assertEqual(normalize_a_share_code("sh600519"), "600519")

    def test_yahoo_symbol(self):
        self.assertEqual(to_yahoo_a_share_symbol("600519"), "600519.SS")
        self.assertEqual(to_yahoo_a_share_symbol("000001"), "000001.SZ")


class TestSectorQueries(unittest.TestCase):
    def test_industry_to_search_queries(self):
        qs = industry_to_search_queries("白酒", name="贵州茅台", code6="600519")
        self.assertGreaterEqual(len(qs), 2)
        self.assertTrue(any("白酒" in q for q in qs))

    def test_merge_news_queries_dedupes(self):
        cfg = {
            "global_news_queries": ["A股 银行", "A股 半导体"],
            "ticker_news_queries": ["A股 银行", "A股 白酒 板块"],
        }
        merged = merge_news_queries(cfg)
        self.assertEqual(len(merged), 3)

    def test_resolve_skips_us_ticker(self):
        cfg = {"market_profile": "us"}
        self.assertEqual(resolve_ticker_news_queries("AAPL", cfg), [])


class TestCnRouting(unittest.TestCase):
    def test_cn_uses_skill_flag(self):
        cfg = {"market_profile": "cn"}
        self.assertTrue(cn_uses_a_share_skill("600584.SS", cfg))

    def test_route_cn_stock_data_no_yfinance_string(self):
        cfg = apply_market_profile({"market_profile": "cn", "company_of_interest": "600584.SS"})
        set_config(cfg)
        # Will call a_share; may return data or skill error text, never Yahoo rate limit msg
        out = route_to_vendor("get_stock_data", "600584.SS", "2026-05-01", "2026-05-10")
        self.assertNotIn("Yahoo Finance rate limited", out)


class TestCnMarketProfile(unittest.TestCase):
    def test_apply_market_profile_sets_vendors(self):
        cfg = {"market_profile": "us", "data_vendors": {"news_data": "yfinance"}}
        apply_market_profile(cfg)
        self.assertEqual(cfg["market_profile"], "us")

        cfg["market_profile"] = "cn"
        apply_market_profile(cfg)
        for cat in ("core_stock_apis", "technical_indicators", "fundamental_data", "news_data"):
            self.assertEqual(cfg["data_vendors"][cat], "a_share")
        self.assertEqual(cfg["output_language"], "Chinese")

    def test_cn_global_news_queries_are_macro_only(self):
        self.assertLessEqual(len(CN_GLOBAL_NEWS_QUERIES), 8)
        joined = " ".join(CN_GLOBAL_NEWS_QUERIES)
        self.assertTrue("央行" in joined or "人民银行" in joined)
        self.assertNotIn("半导体", joined)

    def test_merge_macro_plus_ticker_mode(self):
        cfg = {
            "global_news_mode": "macro_plus_ticker",
            "global_news_queries": list(CN_GLOBAL_NEWS_QUERIES),
            "ticker_news_queries": ["A股 酿酒行业 板块"],
        }
        merged = merge_news_queries(cfg)
        self.assertEqual(len(merged), len(CN_GLOBAL_NEWS_QUERIES) + 1)
        self.assertIn("A股 酿酒行业 板块", merged)

    def test_merge_ticker_only_mode(self):
        cfg = {
            "global_news_mode": "ticker_only",
            "global_news_queries": list(CN_GLOBAL_NEWS_QUERIES),
            "ticker_news_queries": ["A股 酿酒行业 板块"],
        }
        merged = merge_news_queries(cfg)
        self.assertEqual(merged, ["A股 酿酒行业 板块"])

    def test_effective_market_profile_auto(self):
        cfg = {"market_profile": "auto"}
        self.assertEqual(effective_market_profile("600519.SS", cfg), "cn")
        self.assertEqual(effective_market_profile("AAPL", cfg), "us")


if __name__ == "__main__":
    unittest.main()
