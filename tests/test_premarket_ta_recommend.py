"""Tests for premarket TA recommend board name mapping."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.premarket_ta_recommend import board_candidates, _run_board


class TestPremarketTaRecommend(unittest.TestCase):

    def test_board_candidates_security_uses_broker_trust(self):
        canonical, names = board_candidates("证券")
        self.assertEqual(canonical, "证券")
        self.assertIn("券商信托", names)
        self.assertLess(names.index("券商信托"), names.index("证券"))

    def test_board_candidates_battery_has_lithium_aliases(self):
        _, names = board_candidates("电池")
        self.assertIn("电池", names)
        self.assertIn("锂电池", names)

    def test_board_candidates_bank(self):
        _, names = board_candidates("银行")
        self.assertIn("银行", names)

    @patch("scripts.premarket_ta_recommend._run_board_once")
    def test_run_board_falls_back_to_second_candidate(self, mock_once):
        mock_once.side_effect = [
            {"ok": False, "board": "电池", "error": "fail"},
            {"ok": True, "board": "锂电池", "count": 1, "recommendations": [{"code": "002709"}]},
        ]
        out = _run_board("电池", strategy="trend_pullback", top_n=40, validate_top=0, concurrency=1)
        self.assertTrue(out["ok"])
        self.assertEqual(out["board_resolved"], "锂电池")
        self.assertEqual(mock_once.call_count, 2)


if __name__ == "__main__":
    unittest.main()
