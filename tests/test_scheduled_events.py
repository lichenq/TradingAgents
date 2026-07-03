"""Tests for scheduled corporate calendar events (Phase 1/2)."""

import unittest

from tradingagents.dataflows.scheduled_events import (
    build_scheduled_alerts,
    enrich_verified_with_scheduled_events,
    format_scheduled_events_block,
    has_high_restricted_release,
)
from tradingagents.dataflows.trade_date import cn_trading_days_until


class ScheduledEventsTests(unittest.TestCase):
    def test_trading_days_until_weekday_gap(self):
        # Mon 2026-07-06 to Fri 2026-07-10 => 4 sessions if all trading days
        n = cn_trading_days_until("2026-07-03", "2026-07-10")
        self.assertGreaterEqual(n, 1)

    def test_restricted_release_high_severity(self):
        payload = {
            "scheduled_events": {
                "upcoming": [
                    {
                        "type": "restricted_release",
                        "event_date": "2026-07-10",
                        "shares_wan": 98629.21,
                        "market_value_yi": 60.36,
                        "pct_of_float": 5.25,
                        "source": "sina",
                    }
                ]
            }
        }
        alerts = build_scheduled_alerts(payload, "2026-07-03")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "restricted_release")
        self.assertEqual(alerts[0]["severity"], "high")
        self.assertTrue(has_high_restricted_release(alerts))

    def test_format_blocks(self):
        alerts = [
            {
                "severity": "high",
                "event_date": "2026-07-10",
                "label": "限售解禁",
                "trading_days_until": 5,
                "detail": "9.86亿股",
            }
        ]
        md = format_scheduled_events_block(alerts)
        self.assertIn("排期事件", md)
        self.assertIn("限售解禁", md)
        enriched = enrich_verified_with_scheduled_events("【行情硬数据】", alerts)
        self.assertIn("【排期事件硬数据】", enriched)

    def test_past_event_skipped(self):
        payload = {
            "scheduled_events": {
                "upcoming": [
                    {"type": "restricted_release", "event_date": "2020-01-01", "pct_of_float": 10}
                ]
            }
        }
        alerts = build_scheduled_alerts(payload, "2026-07-03")
        self.assertEqual(alerts, [])


if __name__ == "__main__":
    unittest.main()
