"""Tests for premarket sector summary helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.premarket_sector_summary import diff_summaries, _rotation_narrative, build_summary


class TestPremarketDiff(unittest.TestCase):

    def test_diff_rank_up_down_and_narrative(self):
        prev = {
            "top_sectors_by_fund_flow": [
                {"industry": "证券", "rank": 1},
                {"industry": "电池", "rank": 2},
                {"industry": "小金属", "rank": 3},
            ]
        }
        curr = {
            "top_sectors_by_fund_flow": [
                {"industry": "电池", "rank": 1},
                {"industry": "小金属", "rank": 2},
                {"industry": "军工", "rank": 3},
            ]
        }
        delta = diff_summaries(prev, curr)
        self.assertEqual([x["industry"] for x in delta["rank_up"]], ["电池", "小金属"])
        self.assertIn("证券", delta["exit_top"])
        self.assertIn("军工", delta["new_in_top"])
        self.assertTrue(delta["narrative"])

    def test_rotation_narrative_pair(self):
        delta = {
            "exit_top": ["证券"],
            "rank_up": [{"industry": "电池", "from": 2, "to": 1}],
            "new_in_top": [],
            "rank_down": [],
        }
        self.assertEqual(_rotation_narrative(delta), "证券→电池")


class TestBuildSummaryResilience(unittest.TestCase):

    @patch("scripts.premarket_sector_summary._attach_report_ratings", side_effect=lambda picks: picks)
    @patch("scripts.premarket_sector_summary._board_picks_for_sector", return_value=[])
    @patch("scripts.premarket_sector_summary._limit_up_for_sector", return_value=[])
    @patch("scripts.premarket_sector_summary._fetch_market_news", side_effect=RuntimeError("news down"))
    @patch("scripts.premarket_sector_summary._parse_consecutive", return_value=[])
    @patch("scripts.premarket_sector_summary._ta_pullback_hits", return_value={})
    @patch("scripts.premarket_sector_summary._run")
    def test_build_summary_survives_market_news_failure(self, mock_run, *_mocks):
        mock_run.side_effect = [
            {"items": [{"industry": "电池", "main_net_inflow_yi": 1.2, "change_pct": 2.0, "rank": 1}]},
            {"涨停数量": 10},
            [],
            [],
        ]
        data = build_summary()
        self.assertTrue(data.get("ok"))
        self.assertIn("news_catalyst", data)
        self.assertEqual(data["top_sectors_by_fund_flow"][0]["industry"], "电池")


if __name__ == "__main__":
    unittest.main()
