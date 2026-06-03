import json
import unittest
from unittest.mock import patch

from tradingagents.dataflows.cn_prefetch import clear_prefetch_cache, get_prefetched
from tradingagents.dataflows.cn_valuation import (
    _parse_tencent_line,
    fetch_and_cache_cn_valuation,
    format_valuation_markdown,
    require_cn_valuation_ready,
)


SAMPLE_LINE = (
    'v_sh600900="1~长江电力~600900~27.12~26.67~26.66~1106541~757735~348609~'
    "27.12~136~27.11~1752~27.10~756~27.09~258~27.08~598~27.13~201~27.14~2493~"
    "27.15~16766~27.16~7707~27.17~4504~~20260526111905~0.45~1.69~27.15~26.59~"
    "27.12/1106541/2988639991~1106541~298864~0.45~18.39~~27.15~26.59~2.10~"
    "6635.78~6635.78~2.91~29.34~24.00~2.03~-28171~27.01~24.54~19.23~~~0.15~"
    '298863.9991~0.0000~0~ ~GP-A~0.52~-0.48~3.48~15.83~6.50~30.25~25.17~"'
)


class CnValuationParseTests(unittest.TestCase):
    def test_parse_tencent_line_pe_ttm(self):
        parsed = _parse_tencent_line(SAMPLE_LINE)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["code"], "600900")
        self.assertAlmostEqual(parsed["price"], 27.12)
        self.assertAlmostEqual(parsed["pe_ttm"], 18.39)

    def test_format_markdown_contains_ttm(self):
        payload = {
            "ticker": "600900",
            "primary": {
                "name": "长江电力",
                "price": 27.12,
                "pe_ttm": 18.39,
                "pe_annualized_q_eps": 24.54,
                "pb": 2.91,
                "as_of": "20260526111905",
                "source": "腾讯",
            },
            "peers": {},
            "disclaimer": "test",
        }
        md = format_valuation_markdown(payload)
        self.assertIn("18.39", md)
        self.assertIn("TTM", md)

    def test_require_valuation_raises_when_missing(self):
        clear_prefetch_cache()
        cfg = {"require_verified_valuation": True}
        with self.assertRaises(RuntimeError):
            require_cn_valuation_ready("600900", cfg)

    @patch("tradingagents.dataflows.cn_valuation.fetch_cn_valuation_payload")
    def test_fetch_and_cache(self, mock_fetch):
        clear_prefetch_cache()
        mock_fetch.return_value = (
            True,
            {"ticker": "600900", "primary": {"pe_ttm": 18.4, "price": 27.0, "name": "长电"}},
            "## 行情硬数据\n\nTTM PE 18.4×",
        )
        status, ok = fetch_and_cache_cn_valuation("600900", "2026-05-26", {})
        self.assertTrue(ok)
        self.assertIn("TTM PE", get_prefetched("valuation:600900") or "")


if __name__ == "__main__":
    unittest.main()
