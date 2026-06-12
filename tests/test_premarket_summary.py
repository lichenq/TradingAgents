"""Tests for premarket sector summary helpers."""

from __future__ import annotations

import unittest

from scripts.premarket_sector_summary import diff_summaries, _rotation_narrative


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


if __name__ == "__main__":
    unittest.main()
