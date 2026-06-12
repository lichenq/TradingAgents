"""Tests for premarket LLM insight layer."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from scripts import premarket_llm


class TestPremarketLlm(unittest.TestCase):

    def test_extract_json_from_markdown_fence(self):
        raw = '```json\n{"brief": "测试。", "predicted_sectors": []}\n```'
        parsed = premarket_llm._extract_json(raw)
        self.assertEqual(parsed["brief"], "测试。")

    def test_valid_sectors_filters_unknown(self):
        sectors = premarket_llm._valid_sectors([
            {"industry": "电池", "reason": "锂电扩产", "confidence": "high"},
            {"industry": "不存在的板块", "reason": "x"},
        ])
        self.assertEqual(len(sectors), 1)
        self.assertEqual(sectors[0]["industry"], "电池")

    @patch.dict(os.environ, {"PREMARKET_LLM": "0"})
    def test_build_insight_skipped_when_disabled(self):
        out = premarket_llm.build_insight({}, [])
        self.assertTrue(out.get("skipped"))

    @patch.dict(os.environ, {"PREMARKET_LLM": "1"})
    @patch("scripts.premarket_llm._get_llm")
    def test_build_insight_parses_response(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content=json.dumps({
                "brief": "资金主攻电池，AI新闻待确认。",
                "predicted_sectors": [
                    {"industry": "人工智能", "reason": "端侧AI政策", "confidence": "high"},
                ],
                "watch": "9:35看AI是否进TOP",
            }, ensure_ascii=False)
        )
        mock_get_llm.return_value = (mock_llm, "test-model")
        summary = {
            "market_limit_up_count": 90,
            "top_sectors_by_fund_flow": [{"rank": 1, "industry": "电池", "main_net_inflow_yi": 50, "change_pct": 2.1}],
            "news_catalyst": {"predicted_sectors": [{"industry": "电池", "article_count": 2}], "ahead_of_fund_flow": ["人工智能"]},
        }
        out = premarket_llm.build_insight(summary, [{"title": "AI新政"}])
        self.assertTrue(out["ok"])
        self.assertIn("电池", out["brief"])
        self.assertEqual(out["predicted_sectors"][0]["industry"], "人工智能")

    @patch.dict(os.environ, {"PREMARKET_LLM": "1", "PREMARKET_LLM_OPEN": "0"})
    def test_should_run_llm_skips_on_open_compare(self):
        self.assertFalse(premarket_llm.should_run_llm(previous_snapshot={"llm_insight": {"ok": True}}))
        self.assertTrue(premarket_llm.should_run_llm(previous_snapshot=None))

    @patch.dict(os.environ, {"PREMARKET_LLM": "1"})
    def test_reuse_insight_from_previous(self):
        result = {"news_catalyst": {"predicted_sectors": []}}
        prev = {
            "llm_insight": {"ok": True, "brief": "reuse me", "predicted_sectors": []},
            "deep_curation": {"ok": True, "portfolio_summary": "pick A"},
        }
        premarket_llm.reuse_insight_from_previous(result, prev, result["news_catalyst"])
        self.assertEqual(result["llm_insight"]["brief"], "reuse me")
        self.assertEqual(result["deep_curation"]["portfolio_summary"], "pick A")
        cat = {"predicted_sectors": [{"industry": "电池"}]}
        insight = {
            "ok": True,
            "predicted_sectors": [{"industry": "人工智能", "reason": "政策", "confidence": "high"}],
            "watch": "观察AI",
        }
        enriched = premarket_llm.enrich_news_catalyst(cat, insight)
        self.assertIn("llm_predicted", enriched)
        self.assertEqual(enriched["llm_watch"], "观察AI")


if __name__ == "__main__":
    unittest.main()
