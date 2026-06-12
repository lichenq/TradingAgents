"""Tests for WeChat notify formatting."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.premarket_notify_format import format_notify


class TestNotifyFormat(unittest.TestCase):

    def test_evening_has_sections_and_line_breaks(self):
        sample = {
            "market_limit_up_count": 89,
            "limit_up_pool_size": 89,
            "llm_insight": {
                "ok": True,
                "brief": "资金主攻电池。AI新闻待9:35确认。",
            },
            "deep_curation": {
                "ok": True,
                "portfolio_summary": "电池链尚太科技可观察，AI待确认。",
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
            "top_sectors_by_fund_flow": [{
                "rank": 2,
                "industry": "电池",
                "main_net_inflow_yi": 53.2,
                "change_pct": 2.6,
                "limit_up_leaders": [{"name": "雄韬股份"}],
                "board_picks": [{"name": "尚太科技", "change_pct": 7.3}],
                "ta_pullback": [{"name": "尚太科技"}],
            }],
            "consecutive_limit_leaders": [
                {"name": "天地源", "yesterday_boards": 2, "change_pct": -1.2},
            ],
        }
        msg = format_notify(sample, "evening")
        self.assertIn("▎🔥 情绪", msg)
        self.assertIn("▎💬 AI要点", msg)
        self.assertIn("▎📰 新闻前瞻", msg)
        self.assertIn("📊 电池链", msg)
        self.assertIn("✅ 尚太科技", msg)
        self.assertIn("▎💰 资金主线", msg)
        self.assertIn("  · 🔴 涨停 雄韬股份", msg)
        self.assertNotIn("龙头:", msg)
        self.assertGreater(msg.count("\n"), 8)


if __name__ == "__main__":
    unittest.main()
