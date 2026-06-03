"""Tests for the sector mapping table module."""

from __future__ import annotations

import unittest

from tradingagents.dataflows.sector_mapping import (
    all_canonical_names,
    expand_queries,
    get_danginvest_boards,
    get_eastmoney_concepts,
    get_eastmoney_industries,
    get_search_keywords,
    resolve,
)


class TestSectorMapping(unittest.TestCase):

    def test_resolve_existing_mappings(self):
        """All hardcoded mappings from legacy code resolve correctly."""
        cases = {
            "券商信托": "证券",
            "通讯行业": "通信设备",
            "通信行业": "通信设备",
            "消费电子": "电子元件",
            "电机": "电气设备",
            "航天航空": "航空",
            "航空航天": "航空",
            "航天": "航空",
            "电子元件": "电子元件",
            "材料行业": "化工行业",
            "材料": "化工行业",
            "半导体": "半导体",  # identity
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(resolve(raw), expected)

    def test_resolve_unknown(self):
        """Unknown names pass through unchanged."""
        self.assertEqual(resolve("不存在的板块"), "不存在的板块")
        self.assertEqual(resolve(""), "")

    def test_resolve_or_none(self):
        from tradingagents.dataflows.sector_mapping import resolve_or_none
        self.assertEqual(resolve_or_none("券商信托"), "证券")
        self.assertIsNone(resolve_or_none("不存在的板块"))

    def test_search_keywords(self):
        """Keywords should include the canonical name plus related terms."""
        kw = get_search_keywords("半导体")
        self.assertIn("半导体", kw)
        self.assertGreaterEqual(len(kw), 2)

        # Unknown canonical falls back to [name]
        self.assertEqual(get_search_keywords("不存在的"), ["不存在的"])

    def test_danginvest_boards(self):
        """DangInvest board names should be returned correctly."""
        boards = get_danginvest_boards("证券")
        self.assertIsInstance(boards, list)
        self.assertGreater(len(boards), 0)
        self.assertIn("证券", boards)

    def test_eastmoney_industries(self):
        """EastMoney industry names should be returned correctly."""
        inds = get_eastmoney_industries("通信设备")
        self.assertIn("通讯行业", inds)
        self.assertIn("通信行业", inds)

    def test_eastmoney_concepts(self):
        """EastMoney concept names should be returned correctly."""
        concepts = get_eastmoney_concepts("半导体")
        self.assertIn("半导体", concepts)
        self.assertIn("芯片", concepts)

    def test_expand_queries(self):
        """Expand queries should generate alternative keyword versions."""
        queries = ["A股 半导体 板块 政策"]
        expanded = expand_queries(queries)
        self.assertGreater(len(expanded), 1)
        self.assertIn("A股 半导体 板块 政策", expanded)
        # Should contain at least one variant
        found = any("芯片" in q for q in expanded)
        self.assertTrue(found, f"Expected chip variant in expanded: {expanded}")

    def test_expand_queries_empty(self):
        self.assertEqual(expand_queries([]), [])

    def test_all_canonical_names(self):
        names = all_canonical_names()
        self.assertIsInstance(names, list)
        self.assertGreater(len(names), 5)
        self.assertIn("半导体", names)
        self.assertIn("人形机器人", names)
