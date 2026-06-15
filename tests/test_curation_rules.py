"""Tests for Stage-3 hard curation rules."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tradingagents.recommend.curation_rules import (
    CurationContext,
    apply_hard_rules,
    evaluate_hard_rule,
    finalize_actionable_list,
    should_skip_curation,
)


class TestCurationRules(unittest.TestCase):

    def test_hold_rejected_buy_passes(self):
        ctx = CurationContext("results", "2026-06-15", {})
        hold = {"code": "sz002484", "rating": "Hold", "name": "test"}
        buy = {"code": "sz300408", "rating": "Buy", "name": "test2"}
        self.assertFalse(evaluate_hard_rule(hold, ctx)[0])
        self.assertTrue(evaluate_hard_rule(buy, ctx)[0])

    def test_downgrade_buy_blocks(self):
        ctx = CurationContext("results", "2026-06-15", {}, downgrade_buy=True)
        buy = {"code": "sz300408", "rating": "Buy", "name": "t"}
        self.assertFalse(evaluate_hard_rule(buy, ctx)[0])

    def test_finalize_only_actionable(self):
        ctx = CurationContext("results", "2026-06-15", {})
        items = [
            {"code": "sz1", "rating": "Buy", "score": 10},
            {"code": "sz2", "rating": "Overweight", "score": 20},
            {"code": "sz3", "rating": "Hold", "score": 30},
        ]
        out = finalize_actionable_list(items, ctx)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["rating"], "Buy")

    def test_force_curation_env(self):
        with patch.dict("os.environ", {"TRADINGAGENTS_FORCE_CURATION": "1"}):
            self.assertFalse(should_skip_curation(True))

    def test_apply_hard_rules_split(self):
        ctx = CurationContext("results", "2026-06-15", {})
        rows = [
            {"code": "sz1", "rating": "Buy"},
            {"code": "sz2", "rating": "Underweight"},
        ]
        passed, rejected = apply_hard_rules(rows, ctx)
        self.assertEqual(len(passed), 1)
        self.assertEqual(len(rejected), 1)


if __name__ == "__main__":
    unittest.main()
