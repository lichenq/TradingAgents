import unittest
from unittest.mock import patch

from tradingagents.dataflows.cn_valuation import format_valuation_markdown
from tradingagents.dataflows.peer_discovery import (
    format_association_markdown,
    infer_functional_segment,
    pick_theme_concept,
)


class PeerDiscoveryTests(unittest.TestCase):
    def test_pick_theme_concept_prefers_mapped_theme(self):
        concepts = ["沪股通", "机器人", "人形机器人", "专精特新"]
        best, canonical = pick_theme_concept(concepts, industry="自动化设备")
        self.assertEqual(best, "人形机器人")
        self.assertEqual(canonical, "人形机器人")

    def test_infer_segment_harmonic(self):
        seg = infer_functional_segment(
            industry="自动化设备",
            concepts=["人形机器人", "谐波减速器"],
            canonical_theme="人形机器人",
        )
        self.assertEqual(seg, "谐波减速器")

    def test_infer_segment_advanced_packaging(self):
        seg = infer_functional_segment(
            industry="半导体",
            concepts=["Chiplet概念", "先进封装"],
            canonical_theme="半导体",
        )
        self.assertEqual(seg, "先进封装")

    def test_format_association_markdown(self):
        md = format_association_markdown({
            "theme": "人形机器人",
            "segment": "谐波减速器",
            "peer_source": "concept:人形机器人",
            "concept_peers": ["301368", "002896"],
        })
        self.assertIn("动态关联", md)
        self.assertIn("301368", md)
        self.assertIn("卡脖子", md)

    @patch("tradingagents.dataflows.peer_discovery._fetch_board_constituents")
    @patch("tradingagents.dataflows.peer_discovery._fetch_sector_with_concepts")
    def test_discover_functional_peers_merges_concept_first(
        self, mock_sector, mock_board,
    ):
        from tradingagents.dataflows.peer_discovery import discover_functional_peers

        mock_sector.return_value = {
            "name": "绿的谐波",
            "industry": "自动化设备",
            "concepts": ["人形机器人", "谐波减速器", "机器人", "沪股通"],
        }
        mock_board.side_effect = [
            ["688017", "301368", "002896", "002472"],
            ["688017", "300024", "002747"],
        ]
        peers, assoc = discover_functional_peers("688017", limit=4)
        self.assertIn("301368", peers)
        self.assertEqual(assoc["theme"], "人形机器人")
        self.assertEqual(assoc["segment"], "谐波减速器")

    def test_valuation_markdown_includes_association(self):
        md = format_valuation_markdown({
            "ticker": "688017",
            "primary": {"name": "绿的谐波", "price": 50.0, "pe_ttm": 40.0, "source": "腾讯"},
            "peers": {"301368": {"name": "丰立智能", "price": 30.0, "pe_ttm": 35.0}},
            "association": {
                "theme": "人形机器人",
                "segment": "谐波减速器",
                "concept_peers": ["301368"],
            },
            "disclaimer": "test",
        })
        self.assertIn("动态关联", md)
        self.assertIn("功能同业", md)
        self.assertIn("301368", md)


if __name__ == "__main__":
    unittest.main()
