import unittest
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from tradingagents.graph.storage import (
    init_db,
    save_report_to_sqlite,
    save_recommendation_to_sqlite,
    get_reports_from_sqlite,
    get_recommendations_from_sqlite,
    save_backtest_audit,
    query_backtest_audits,
)


class TestSQLiteStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_trading_agents.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_and_save_flow(self):
        # 1. Initialize DB
        init_db(self.db_path)
        self.assertTrue(self.db_path.exists())

        # 2. Save recommendation
        rec_item = {
            "code": "sz300604",
            "name": "长川科技",
            "score": 85.5,
            "price": 229.19,
            "rating": "Buy",
            "metrics": {"ma10": 220.0, "ma30": 190.0},
            "reason": "Test reason",
        }
        save_recommendation_to_sqlite(rec_item, "trend_pullback", "2026-05-27", db_path=self.db_path)

        recs = get_recommendations_from_sqlite("2026-05-27", "trend_pullback", db_path=self.db_path)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["code"], "sz300604")
        self.assertEqual(recs[0]["metrics"]["ma10"], 220.0)

        # 3. Save report
        final_state = {
            "market_report": "market text",
            "sentiment_report": "sentiment text",
            "news_report": "news text",
            "fundamentals_report": "fundamentals text",
            "final_trade_decision": "final text rating: Buy",
            "final_trade_decision_rating": "Buy",
            "investment_debate_state": {
                "bull_history": "bull history text",
                "bear_history": "bear history text",
            },
            "risk_debate_state": {
                "aggressive_history": "aggressive risk text",
                "conservative_history": "conservative risk text",
                "neutral_history": "neutral risk text",
            },
        }
        save_report_to_sqlite(final_state, "300604", "2026-05-27", db_path=self.db_path, complete_report_text="complete text")

        reports = get_reports_from_sqlite("sz300604", "2026-05-27", db_path=self.db_path)
        self.assertEqual(len(reports), 1)
        self.assertEqual(recs[0]["code"], "sz300604")
        self.assertEqual(reports[0]["ticker"], "sz300604")
        self.assertEqual(reports[0]["market_report"], "market text")
        self.assertEqual(reports[0]["news_report"], "news text")
        self.assertEqual(reports[0]["fundamentals_report"], "fundamentals text")
        self.assertEqual(reports[0]["bull_history"], "bull history text")
        self.assertEqual(reports[0]["aggressive_history"], "aggressive risk text")
        self.assertEqual(reports[0]["conservative_history"], "conservative risk text")
        self.assertEqual(reports[0]["neutral_history"], "neutral risk text")
        self.assertEqual(reports[0]["complete_report"], "complete text")

        # 4. Save and query backtest audits
        save_backtest_audit(
            results_dir=self.temp_dir.name,
            ticker="sz300604",
            recommendation_date="2026-05-27",
            audit_date="2026-05-30",
            days_elapsed=3,
            initial_price=229.19,
            end_price=240.0,
            raw_return=0.0471,
            reflection="Perfect upward momentum continuation.",
            db_path=self.db_path
        )

        audits = query_backtest_audits(self.temp_dir.name, ticker="sz300604", db_path=self.db_path)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["ticker"], "sz300604")
        self.assertEqual(audits[0]["recommendation_date"], "2026-05-27")
        self.assertEqual(audits[0]["days_elapsed"], 3)
        self.assertEqual(audits[0]["initial_price"], 229.19)
        self.assertEqual(audits[0]["end_price"], 240.0)
        self.assertAlmostEqual(audits[0]["raw_return"], 0.0471)
        self.assertEqual(audits[0]["reflection"], "Perfect upward momentum continuation.")


if __name__ == "__main__":
    unittest.main()
