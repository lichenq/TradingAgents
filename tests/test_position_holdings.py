import unittest

from tradingagents.agents.utils.position_holdings import (
    enrich_verified_with_position_holdings,
    extract_price_from_verified,
    format_position_holdings_markdown,
    get_holdings_from_config,
    parse_position_cost,
    parse_position_shares,
)


class PositionHoldingsTests(unittest.TestCase):
    def test_parse_cost_and_shares(self):
        self.assertEqual(parse_position_cost("13.84"), 13.84)
        self.assertEqual(parse_position_shares(1000), 1000)
        self.assertIsNone(parse_position_cost(0))
        self.assertIsNone(parse_position_shares(-1))

    def test_extract_price(self):
        md = "- **现价**: 13.24 元\n"
        self.assertEqual(extract_price_from_verified(md), 13.24)

    def test_format_pnl_chinese(self):
        block = format_position_holdings_markdown(
            13.84, 1000, current_price=13.24, use_chinese=True
        )
        self.assertIn("13.84", block)
        self.assertIn("1000", block)
        self.assertIn("浮动盈亏", block)
        self.assertIn("-600.00", block)

    def test_enrich_sets_held_and_appends(self):
        verified = "## 行情硬数据\n\n- **现价**: 13.24 元\n"
        config = {
            "position_cost": 13.84,
            "position_shares": 1000,
            "position_context": "empty",
            "output_language": "Chinese",
        }
        out = enrich_verified_with_position_holdings(verified, config)
        self.assertEqual(config["position_context"], "held")
        self.assertIn("投资者持仓", out)
        self.assertIn("行情硬数据", out)

    def test_get_holdings_from_config(self):
        cfg = {"position_cost": 10.5, "position_shares": 200}
        self.assertEqual(get_holdings_from_config(cfg), (10.5, 200))


if __name__ == "__main__":
    unittest.main()
