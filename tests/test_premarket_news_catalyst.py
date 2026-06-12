"""Tests for news → sector catalyst matching."""

from __future__ import annotations

import unittest

from scripts.premarket_news_catalyst import (
    ahead_of_fund_flow,
    build_news_catalyst,
    build_watch_if,
    catalyst_confirmed,
    match_news_to_sectors,
    rank_predicted_sectors,
)


class TestNewsCatalyst(unittest.TestCase):

    def test_match_ai_and_battery_news(self):
        items = [
            {
                "id": 1,
                "title": "工信部新政指向端侧推理 多光谱AI赛道迎商业化换挡期",
                "content": "人工智能+信息通信",
                "published_at": "2026-06-12 13:49:11",
            },
            {
                "id": 2,
                "title": "",
                "content": "锂电池产能扩张，固态电池试点加速",
                "published_at": "2026-06-12 13:40:00",
            },
        ]
        hits = match_news_to_sectors(items)
        self.assertIn("人工智能", hits)
        self.assertIn("电池", hits)

    def test_ahead_of_fund_flow(self):
        predicted = [{"industry": "电池"}, {"industry": "人工智能"}]
        flow = ["证券", "银行", "小金属"]
        ahead = ahead_of_fund_flow(predicted, flow)
        self.assertIn("电池", ahead)
        self.assertIn("人工智能", ahead)

    def test_catalyst_confirmed_on_rank_up(self):
        prev = {"predicted_sectors": [{"industry": "电池"}, {"industry": "证券"}]}
        delta = {"rank_up": [{"industry": "电池", "from": 2, "to": 1}], "new_in_top": []}
        self.assertEqual(catalyst_confirmed(prev, delta), ["电池"])

    def test_build_watch_if_ahead(self):
        predicted = [{"industry": "电池"}, {"industry": "人工智能"}]
        text = build_watch_if(predicted, ["电池"])
        self.assertIn("电池", text)
        self.assertIn("9:35", text)

    def test_rank_dedupes_by_article_id(self):
        items = [
            {"id": 9, "title": "半导体设备国产化", "content": "芯片产业链", "published_at": ""},
            {"id": 9, "title": "半导体设备国产化", "content": "芯片产业链", "published_at": ""},
        ]
        out = build_news_catalyst(items, fund_flow_industries=[])
        semi = next(p for p in out["predicted_sectors"] if p["industry"] == "半导体")
        self.assertEqual(semi["article_count"], 1)

    def test_bank_noise_rejected_in_content_only(self):
        items = [{
            "id": 100,
            "title": "",
            "content": "全球多家银行据悉遏制对冲基金部分杠杆押注",
            "published_at": "",
        }]
        hits = match_news_to_sectors(items)
        self.assertNotIn("银行", hits)

    def test_bank_matches_when_in_title(self):
        items = [{
            "id": 101,
            "title": "银行板块午后拉升",
            "content": "多家国有大行走强",
            "published_at": "",
        }]
        hits = match_news_to_sectors(items)
        self.assertIn("银行", hits)

    def test_material_noise_rejected_in_content(self):
        items = [{
            "id": 102,
            "title": "",
            "content": "关键原材料定价过高或迫使芯片制造商转向替代产品",
            "published_at": "",
        }]
        hits = match_news_to_sectors(items)
        self.assertNotIn("化工行业", hits)
        self.assertIn("半导体", hits)

    def test_article_limited_to_two_sectors(self):
        items = [{
            "id": 103,
            "title": "人工智能芯片半导体设备协同推进",
            "content": "AI算力 芯片 半导体产业链",
            "published_at": "",
        }]
        hits = match_news_to_sectors(items)
        total = sum(len(v) for v in hits.values())
        self.assertLessEqual(total, 2)


if __name__ == "__main__":
    unittest.main()
