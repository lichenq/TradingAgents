"""Tests for WeChat notify formatting (rotation mode)."""

from __future__ import annotations

import unittest

from scripts.premarket_notify_format import (
    _tomorrow_action_line,
    format_notify,
    format_rotation_mainline,
)


class TestNotifyFormat(unittest.TestCase):

    def test_evening_rotation_sections(self):
        sample = {
            "market_limit_up_count": 89,
            "limit_up_pool_size": 89,
            "llm_insight": {
                "ok": True,
                "predicted_sectors": [
                    {"industry": "人工智能", "reason": "端侧AI政策催化", "confidence": "high"},
                ],
            },
            "deep_curation": {
                "portfolio_summary": "应被忽略",
                "recommended": [{"name": "尚太科技", "reviewed_rating": "Overweight"}],
            },
            "news_catalyst": {
                "predicted_sectors": [
                    {"industry": "人工智能", "article_count": 6, "headlines": ["AI新政"]},
                ],
                "llm_predicted": [
                    {"industry": "人工智能", "reason": "端侧AI政策催化", "confidence": "high"},
                ],
                "ahead_of_fund_flow": ["人工智能"],
            },
            "top_sectors_by_fund_flow": [
                {
                    "rank": 1,
                    "industry": "证券",
                    "main_net_inflow_yi": 69.7,
                    "change_pct": 3.9,
                    "limit_up_leaders": [],
                    "board_picks": [],
                },
                {
                    "rank": 2,
                    "industry": "电池",
                    "main_net_inflow_yi": 53.2,
                    "change_pct": 2.6,
                    "limit_up_leaders": [{"name": "雄韬股份"}],
                    "board_picks": [{"name": "尚太科技", "change_pct": 7.3}],
                    "ta_pullback": [{"name": "尚太科技"}],
                },
            ],
            "consecutive_limit_leaders": [
                {"name": "天地源", "yesterday_boards": 2, "change_pct": -1.2},
                {"name": "康强电子", "yesterday_boards": 2, "change_pct": 2.4},
            ],
        }
        msg = format_notify(sample, "evening")
        self.assertIn("▎🔥 情绪", msg)
        self.assertIn("▎🎯 明日动作", msg)
        self.assertIn("▎📰 新闻前瞻", msg)
        self.assertIn("▎💰 资金主线", msg)
        self.assertIn("主盯 电池", msg)
        self.assertIn("观察 人工智能", msg)
        self.assertIn("搭台 证券", msg)
        self.assertIn("⏸️ 仅搭台（无票）: 证券", msg)
        self.assertIn("  · 🔴 涨停 雄韬股份", msg)
        self.assertNotIn("▎💬 AI要点", msg)
        self.assertNotIn("尚太科技 [Overweight]", msg)
        self.assertNotIn("天地源", msg)
        self.assertIn("康强电子 2板", msg)
        self.assertNotIn("龙头:", msg)
        self.assertGreater(msg.count("\n"), 8)

    def test_rotation_mainline_skips_empty_and_keeps_rank_order(self):
        sectors = [
            {"rank": 1, "industry": "证券", "main_net_inflow_yi": 70, "change_pct": 3.9},
            {"rank": 2, "industry": "银行", "main_net_inflow_yi": 57, "change_pct": 1.4,
             "board_picks": [{"name": "平安银行", "change_pct": 2.7}]},
            {"rank": 3, "industry": "电池", "main_net_inflow_yi": 54, "change_pct": 2.7,
             "limit_up_leaders": [{"name": "雄韬股份"}]},
            {"rank": 4, "industry": "小金属", "main_net_inflow_yi": 38, "change_pct": 3.2,
             "limit_up_leaders": [{"name": "金钼股份"}]},
        ]
        lines = format_rotation_mainline(sectors)
        text = "\n".join(lines)
        self.assertIn("2. 银行", text)
        self.assertIn("3. 电池", text)
        self.assertIn("4. 小金属", text)
        self.assertNotIn("1. 证券", text)
        self.assertIn("仅搭台（无票）: 证券", text)

    def test_tomorrow_action_line(self):
        data = {
            "top_sectors_by_fund_flow": [
                {"rank": 1, "industry": "证券", "limit_up_leaders": [], "board_picks": []},
                {"rank": 2, "industry": "电池", "limit_up_leaders": [{"name": "A"}],
                 "board_picks": []},
                {"rank": 3, "industry": "小金属", "limit_up_leaders": [{"name": "B"}],
                 "board_picks": []},
            ],
            "news_catalyst": {"ahead_of_fund_flow": ["人工智能", "半导体"]},
        }
        action = _tomorrow_action_line(data)
        self.assertIn("主盯 电池 / 小金属", action)
        self.assertIn("观察 人工智能", action)
        self.assertIn("搭台 证券", action)


if __name__ == "__main__":
    unittest.main()
