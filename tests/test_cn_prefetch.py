import unittest
from unittest.mock import patch

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.cn_prefetch import run_cn_prefetch


class CnPrefetchNewsTests(unittest.TestCase):
    def test_global_news_args_not_date_strings(self):
        cfg = DEFAULT_CONFIG.copy()
        cfg["market_profile"] = "cn"
        set_config(cfg)
        calls = []

        def fake_route(method, *args):
            calls.append((method, args))
            return "data"

        patches = [
            patch(
                "tradingagents.dataflows.sector_queries.fetch_sector_payload",
                return_value={"name": "中芯国际", "industry": "半导体"},
            ),
            patch(
                "tradingagents.dataflows.a_share.get_a_share_fundamentals",
                return_value="fundamentals ok",
            ),
            patch(
                "tradingagents.dataflows.cn_sentiment.fetch_xueqiu_block",
                return_value="xueqiu ok",
            ),
            patch(
                "tradingagents.dataflows.a_share_runner.run_script",
                return_value=(True, "", {
                    "code": "688981",
                    "scheduled_events": {"upcoming": [], "count": 0},
                    "performance": {"count": 0},
                    "holder_change_buyback": {"count": 0},
                    "regulatory": {"count": 0},
                    "major_contracts": {"count": 0},
                    "sentiment": {"count": 0},
                }),
            ),
            patch(
                "tradingagents.dataflows.cn_technical.fetch_and_cache_cn_technical",
                return_value=("ok · MACD_DIF -0.20", True),
            ),
            patch(
                "tradingagents.dataflows.a_share._build_a_share_ohlcv_block",
                return_value="time,open,high,low,close,volume,pctChg\n2026-07-03,1,2,3,4,5,6",
            ),
            patch(
                "tradingagents.dataflows.interface.route_to_vendor",
                side_effect=fake_route,
            ),
        ]
        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            lines = run_cn_prefetch("688981.SS", "2026-05-23", cfg, max_workers=2)

        self.assertTrue(any("news: ok" in ln for ln in lines))
        self.assertFalse(any("预取失败" in ln for ln in lines))
        macro = [c for c in calls if c[0] == "get_global_news"][0]
        self.assertEqual(macro[1][0], "2026-05-23")
        self.assertIsInstance(macro[1][1], int)
        self.assertIsInstance(macro[1][2], int)


if __name__ == "__main__":
    unittest.main()
