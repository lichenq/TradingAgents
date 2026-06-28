"""Tests for audit recommendation selection by trading sessions."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.auto_backtest_audit import get_recommendations_to_audit
from tradingagents.graph.storage import init_db, save_recommendation


class TestAuditRecommendationQuery(unittest.TestCase):

    def test_filters_by_trading_sessions_not_calendar_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_db(tmp)
            save_recommendation(
                tmp,
                "2026-06-12",
                "trend_pullback",
                {
                    "code": "sz300408",
                    "name": "三环集团",
                    "score": 80.0,
                    "price": 40.0,
                    "rating": "Buy",
                    "reason": "trend",
                    "metrics": {},
                    "report_paths": {},
                    "is_final": 1,
                },
            )
            save_recommendation(
                tmp,
                "2026-06-10",
                "trend_pullback",
                {
                    "code": "sz002484",
                    "name": "江海股份",
                    "score": 70.0,
                    "price": 80.0,
                    "rating": "Buy",
                    "reason": "hot",
                    "metrics": {},
                    "report_paths": {},
                    "is_final": 1,
                },
            )
            save_recommendation(
                tmp,
                "2026-06-08",
                "trend_pullback",
                {
                    "code": "sz000001",
                    "name": "HoldOnly",
                    "score": 60.0,
                    "price": 10.0,
                    "rating": "Hold",
                    "reason": "watch",
                    "metrics": {},
                    "report_paths": {},
                    "is_final": 1,
                },
            )
            db_path = f"{tmp}/trading_agents.db"
            conn = sqlite3.connect(db_path)

            with patch(
                "scripts.auto_backtest_audit.cn_trading_sessions_after",
                side_effect=lambda rec_date, as_of: {
                    ("2026-06-12", date(2026, 6, 15)): 1,
                    ("2026-06-10", date(2026, 6, 15)): 3,
                    ("2026-06-08", date(2026, 6, 15)): 5,
                }[(rec_date, as_of)],
            ):
                ready = get_recommendations_to_audit(conn, audit_days=3, as_of=date(2026, 6, 15))

            conn.close()
            codes = {r["code"] for r in ready}
            self.assertIn("sz002484", codes)
            self.assertNotIn("sz300408", codes)
            self.assertNotIn("sz000001", codes)


if __name__ == "__main__":
    unittest.main()
