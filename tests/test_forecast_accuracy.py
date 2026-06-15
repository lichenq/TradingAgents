"""Tests for forecast category accuracy tracking."""

from __future__ import annotations

import json
import tempfile
import unittest

from tradingagents.dataflows.forecast_accuracy import (
    aggregate_category_accuracy,
    record_forecast_accuracy,
)


class TestForecastAccuracy(unittest.TestCase):

    def test_record_and_aggregate(self):
        with tempfile.TemporaryDirectory() as tmp:
            forecast = {
                "_meta": {"trade_date": "2026-06-14"},
                "半导体": {
                    "category": "SYSTEMIC_LIQUIDATION",
                    "probability": 0.8,
                },
                "电力": {
                    "category": "MOM_INFLOW",
                    "probability": 0.7,
                },
            }
            sectors = [
                {"industry": "半导体", "main_net_inflow_yi": -5.0},
                {"industry": "电力", "main_net_inflow_yi": 3.0},
            ]
            out = record_forecast_accuracy(forecast, sectors, results_dir=tmp)
            self.assertTrue(out["recorded"])
            agg = aggregate_category_accuracy(tmp)
            self.assertIn("SYSTEMIC_LIQUIDATION", agg["by_category"])
            self.assertEqual(agg["by_category"]["SYSTEMIC_LIQUIDATION"]["hit_rate"], 1.0)
            self.assertEqual(agg["by_category"]["MOM_INFLOW"]["hit_rate"], 1.0)

            record_forecast_accuracy(
                forecast,
                [{"industry": "半导体", "main_net_inflow_yi": 10.0}],
                results_dir=tmp,
            )
            agg2 = aggregate_category_accuracy(tmp)
            self.assertLess(
                agg2["by_category"]["SYSTEMIC_LIQUIDATION"]["hit_rate"],
                1.0,
            )


if __name__ == "__main__":
    unittest.main()
