"""Tests for rotation forecast load, staleness, and auto board filter."""

from __future__ import annotations

import unittest
from datetime import date

from tradingagents.dataflows.rotation_forecast import (
    filter_hot_industries_by_forecast,
    is_stale_forecast,
    lookup_forecast_entry,
    sector_entries,
)


class TestRotationForecast(unittest.TestCase):

    def test_sector_entries_skips_meta(self):
        raw = {
            "_meta": {"trade_date": "2026-06-15"},
            "半导体": {"category": "NORMAL"},
        }
        self.assertEqual(list(sector_entries(raw).keys()), ["半导体"])

    def test_filter_skips_danger_without_inflow(self):
        items = [
            {"industry": "通信设备", "main_net_inflow_yi": 0.5},
            {"industry": "半导体", "main_net_inflow_yi": 4.0},
        ]
        fc = {
            "通信设备": {"category": "SYSTEMIC_LIQUIDATION"},
            "半导体": {"category": "NORMAL"},
        }
        selected, notes = filter_hot_industries_by_forecast(items, fc, top_n=5)
        self.assertEqual(selected, ["半导体"])
        self.assertTrue(any("避雷跳过" in n for n in notes))

    def test_filter_t0_override_keeps_strong_inflow(self):
        items = [{"industry": "通信设备", "main_net_inflow_yi": 11.38}]
        fc = {"通信设备": {"category": "SYSTEMIC_LIQUIDATION"}}
        selected, notes = filter_hot_industries_by_forecast(items, fc, top_n=5)
        self.assertEqual(selected, ["通信设备"])
        self.assertTrue(any("T0 覆盖" in n for n in notes))

    def test_is_stale_legacy_update_time(self):
        fc = {
            "银行": {"category": "MOM_INFLOW", "update_time": "2020-01-02 21:00:00"},
        }
        self.assertTrue(is_stale_forecast(fc, date(2026, 6, 15)))

    def test_lookup_by_alias(self):
        fc = {"元器件": {"category": "NORMAL"}}
        entry = lookup_forecast_entry("元件", fc)
        self.assertEqual(entry["category"], "NORMAL")


if __name__ == "__main__":
    unittest.main()
