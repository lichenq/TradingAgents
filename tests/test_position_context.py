import unittest
from unittest.mock import patch

from tradingagents.agents.utils.position_context import (
    get_position_assumption_instruction,
    get_position_context,
    get_rating_scale_guidance,
    is_empty_position,
)


class PositionContextTests(unittest.TestCase):
    @patch("tradingagents.dataflows.config.get_config")
    def test_default_empty(self, mock_cfg):
        mock_cfg.return_value = {"position_context": "empty", "output_language": "English"}
        self.assertEqual(get_position_context(), "empty")
        self.assertTrue(is_empty_position())
        scale = get_rating_scale_guidance()
        self.assertIn("do not open", scale.lower())
        self.assertIn("flat", scale.lower())

    @patch("tradingagents.dataflows.config.get_config")
    def test_held_context(self, mock_cfg):
        mock_cfg.return_value = {"position_context": "held", "output_language": "English"}
        self.assertFalse(is_empty_position())
        scale = get_rating_scale_guidance()
        self.assertIn("trim", scale.lower())

    @patch("tradingagents.dataflows.config.get_config")
    def test_chinese_empty_assumption(self, mock_cfg):
        mock_cfg.return_value = {"position_context": "empty", "output_language": "Chinese"}
        block = get_position_assumption_instruction()
        self.assertIn("空仓", block)
        self.assertIn("不建仓", block)

    @patch("tradingagents.dataflows.config.get_config")
    def test_retail_context(self, mock_cfg):
        mock_cfg.return_value = {"position_context": "retail", "output_language": "English"}
        from tradingagents.agents.utils.position_context import is_retail_position
        self.assertFalse(is_empty_position())
        self.assertTrue(is_retail_position())
        scale = get_rating_scale_guidance()
        self.assertIn("retail", scale.lower())
        self.assertIn("tranche", scale.lower())
        self.assertNotIn("do not open", scale.lower())

    @patch("tradingagents.dataflows.config.get_config")
    def test_retail_chinese(self, mock_cfg):
        mock_cfg.return_value = {"position_context": "retail", "output_language": "Chinese"}
        block = get_position_assumption_instruction()
        self.assertIn("个人投资者", block)
        self.assertIn("分批", block)


if __name__ == "__main__":
    unittest.main()
