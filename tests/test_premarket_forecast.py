"""Tests for sector rotation forecast attachment."""

from __future__ import annotations

import unittest

from scripts.premarket_forecast import attach_forecast, lookup_forecast_entry


class TestPremarketForecast(unittest.TestCase):

    def test_lookup_by_industry_name(self):
        fc = {"电池": {"category": "MOM_INFLOW", "probability": "HIGH"}}
        entry = lookup_forecast_entry("电池", fc)
        self.assertEqual(entry["category"], "MOM_INFLOW")

    def test_attach_adds_per_sector_forecast(self):
        sectors = [{"industry": "电池", "rank": 1}]
        fc = {"电池": {"category": "MOM_INFLOW", "probability": "HIGH", "action_advice": "主攻"}}
        layer = attach_forecast(sectors, fc)
        self.assertTrue(layer["ok"])
        self.assertIn("forecast", sectors[0])
        self.assertEqual(sectors[0]["forecast"]["category_label"], "强趋势流入")


if __name__ == "__main__":
    unittest.main()
