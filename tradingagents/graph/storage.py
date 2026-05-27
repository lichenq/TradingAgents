"""SQLite storage database and operations for TradingAgents reports and recommendations."""

from __future__ import annotations

import json
import sqlite3
import datetime
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def get_db_path(results_dir: str | Path) -> Path:
    """Return the absolute path to the local SQLite database file."""
    path = Path(results_dir)
    if path.suffix == ".db":
        return path
    path.mkdir(parents=True, exist_ok=True)
    return path / "trading_agents.db"


def _resolve_db(results_dir: str | Path, db_path: Optional[str | Path] = None) -> Path:
    if db_path:
        return Path(db_path)
    return get_db_path(results_dir)


def init_db(results_dir_or_db_path: str | Path) -> None:
    """Initialize the SQLite database with the required schema."""
    p = Path(results_dir_or_db_path)
    if p.suffix == ".db":
        db_path = p
    else:
        db_path = get_db_path(p)
        
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        
        # Table: recommendations (Stage 1 & 2 recommendations outputs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT,
                strategy TEXT,
                code TEXT,
                name TEXT,
                score REAL,
                price REAL,
                rating TEXT,
                reason TEXT,
                metrics TEXT,
                report_paths TEXT,
                created_at TEXT
            )
        """)
        
        # Table: reports (Stage 2 deep multi-agent reports)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT,
                trade_date TEXT,
                rating TEXT,
                complete_report TEXT,
                final_trade_decision TEXT,
                investment_plan TEXT,
                market_report TEXT,
                sentiment_report TEXT,
                bull_history TEXT,
                bear_history TEXT,
                created_at TEXT,
                UNIQUE(ticker, trade_date)
            )
        """)

        # Table: backtest_audits (Automated backtesting and AI reflection results)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backtest_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT,
                recommendation_date TEXT,
                audit_date TEXT,
                days_elapsed INTEGER,
                initial_price REAL,
                end_price REAL,
                raw_return REAL,
                reflection TEXT,
                created_at TEXT,
                UNIQUE(ticker, recommendation_date, days_elapsed)
            )
        """)
        
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to initialize SQLite database: {e}")
    finally:
        conn.close()


def save_recommendation(
    results_dir: str | Path,
    trade_date: str,
    strategy: str,
    rec: Dict[str, Any],
    db_path: Optional[str | Path] = None
) -> None:
    """Save or update a single recommendation item in the database."""
    resolved_db = _resolve_db(results_dir, db_path)
    init_db(resolved_db)
    conn = sqlite3.connect(str(resolved_db))
    try:
        cursor = conn.cursor()
        
        # Serialize dict structures
        metrics_json = json.dumps(rec.get("metrics") or {}, ensure_ascii=False)
        report_paths_json = json.dumps(rec.get("report_paths") or {}, ensure_ascii=False)
        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Delete pre-existing record for same trade_date + code + strategy to avoid duplicates
        cursor.execute(
            "DELETE FROM recommendations WHERE trade_date = ? AND code = ? AND strategy = ?",
            (trade_date, rec.get("code"), strategy)
        )
        
        cursor.execute("""
            INSERT INTO recommendations (
                trade_date, strategy, code, name, score, price, rating, reason, metrics, report_paths, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_date,
            strategy,
            rec.get("code"),
            rec.get("name"),
            rec.get("score"),
            rec.get("price"),
            rec.get("rating"),
            rec.get("reason"),
            metrics_json,
            report_paths_json,
            created_at
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to save recommendation to SQLite: {e}")
    finally:
        conn.close()


def save_report(
    results_dir: str | Path,
    ticker: str,
    trade_date: str,
    rating: str,
    complete_report: str,
    final_trade_decision: str = "",
    investment_plan: str = "",
    market_report: str = "",
    sentiment_report: str = "",
    bull_history: str = "",
    bear_history: str = "",
    db_path: Optional[str | Path] = None
) -> None:
    """Save or replace a deep multi-agent report in the database."""
    resolved_db = _resolve_db(results_dir, db_path)
    init_db(resolved_db)
    conn = sqlite3.connect(str(resolved_db))
    try:
        cursor = conn.cursor()
        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            INSERT OR REPLACE INTO reports (
                ticker, trade_date, rating, complete_report, final_trade_decision, investment_plan,
                market_report, sentiment_report, bull_history, bear_history, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker,
            trade_date,
            rating,
            complete_report,
            final_trade_decision,
            investment_plan,
            market_report,
            sentiment_report,
            bull_history,
            bear_history,
            created_at
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to save report to SQLite: {e}")
    finally:
        conn.close()


def query_recommendations(
    results_dir: str | Path,
    trade_date: Optional[str] = None,
    strategy: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Query recommendations from SQLite."""
    init_db(results_dir)
    db_path = get_db_path(results_dir)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM recommendations WHERE 1=1"
        params: List[Any] = []
        
        if trade_date:
            query += " AND trade_date = ?"
            params.append(trade_date)
        if strategy:
            query += " AND strategy = ?"
            params.append(strategy)
            
        query += " ORDER BY score DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        results = []
        for row in rows:
            item = dict(row)
            item["metrics"] = json.loads(item["metrics"] or "{}")
            item["report_paths"] = json.loads(item["report_paths"] or "{}")
            results.append(item)
        return results
    except Exception as e:
        logger.error(f"Failed to query recommendations from SQLite: {e}")
        return []
    finally:
        conn.close()


def query_report(
    results_dir: str | Path,
    ticker: str,
    trade_date: str
) -> Optional[Dict[str, Any]]:
    """Retrieve a single report from SQLite."""
    init_db(results_dir)
    db_path = get_db_path(results_dir)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM reports WHERE ticker = ? AND trade_date = ?",
            (ticker, trade_date)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"Failed to query report from SQLite: {e}")
        return None
    finally:
        conn.close()


def save_report_to_sqlite(
    final_state: Dict[str, Any],
    ticker: str,
    trade_date: str,
    complete_report_text: str = "",
    db_path: Optional[str | Path] = None
) -> None:
    """Convenience wrapper for save_report used by report_export.py."""
    from tradingagents.default_config import DEFAULT_CONFIG
    results_dir = final_state.get("results_dir") or DEFAULT_CONFIG["results_dir"]
    rating = final_state.get("final_trade_decision_rating") or final_state.get("final_trade_decision") or ""
    if isinstance(rating, str) and "Rating:" in rating:
        # Try to parse rating from final decision markdown
        for line in rating.splitlines():
            if "rating" in line.lower() or "decision:" in line.lower():
                rating = line
                break
    final_trade_decision = final_state.get("final_trade_decision") or ""
    investment_plan = final_state.get("investment_plan") or ""
    
    market_report = final_state.get("market_report") or ""
    sentiment_report = final_state.get("sentiment_report") or ""
    
    debate_state = final_state.get("investment_debate_state") or {}
    bull_history = debate_state.get("bull_history") or ""
    bear_history = debate_state.get("bear_history") or ""
    
    save_report(
        results_dir=results_dir,
        ticker=ticker,
        trade_date=trade_date,
        rating=str(rating)[:50],
        complete_report=complete_report_text,
        final_trade_decision=final_trade_decision,
        investment_plan=investment_plan,
        market_report=market_report,
        sentiment_report=sentiment_report,
        bull_history=bull_history,
        bear_history=bear_history,
        db_path=db_path
    )


def save_recommendation_to_sqlite(
    rec: Dict[str, Any],
    strategy: str,
    trade_date: str,
    db_path: Optional[str | Path] = None
) -> None:
    """Convenience wrapper for save_recommendation used by run_recommend.py."""
    from tradingagents.default_config import DEFAULT_CONFIG
    results_dir = DEFAULT_CONFIG["results_dir"]
    save_recommendation(
        results_dir=results_dir,
        trade_date=trade_date,
        strategy=strategy,
        rec=rec,
        db_path=db_path
    )


def get_reports_from_sqlite(
    ticker: str,
    trade_date: str,
    db_path: Optional[str | Path] = None
) -> List[Dict[str, Any]]:
    """Retrieve deep multi-agent reports from SQLite (matches test expected return list format)."""
    from tradingagents.default_config import DEFAULT_CONFIG
    resolved_db = _resolve_db(DEFAULT_CONFIG["results_dir"], db_path)
    init_db(resolved_db)
    
    conn = sqlite3.connect(str(resolved_db))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM reports WHERE ticker = ? AND trade_date = ?",
            (ticker, trade_date)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to query reports from SQLite: {e}")
        return []
    finally:
        conn.close()


def get_recommendations_from_sqlite(
    trade_date: str,
    strategy: str,
    db_path: Optional[str | Path] = None
) -> List[Dict[str, Any]]:
    """Retrieve recommendations from SQLite (matches test expected return list format)."""
    from tradingagents.default_config import DEFAULT_CONFIG
    resolved_db = _resolve_db(DEFAULT_CONFIG["results_dir"], db_path)
    init_db(resolved_db)
    
    conn = sqlite3.connect(str(resolved_db))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM recommendations WHERE trade_date = ? AND strategy = ? ORDER BY score DESC",
            (trade_date, strategy)
        )
        rows = cursor.fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["metrics"] = json.loads(item["metrics"] or "{}")
            item["report_paths"] = json.loads(item["report_paths"] or "{}")
            results.append(item)
        return results
    except Exception as e:
        logger.error(f"Failed to query recommendations from SQLite: {e}")
        return []
    finally:
        conn.close()


def save_backtest_audit(
    results_dir: str | Path,
    ticker: str,
    recommendation_date: str,
    audit_date: str,
    days_elapsed: int,
    initial_price: float,
    end_price: float,
    raw_return: float,
    reflection: str,
    db_path: Optional[str | Path] = None
) -> None:
    """Save or replace a backtest audit with its AI reflection in SQLite."""
    resolved_db = _resolve_db(results_dir, db_path)
    init_db(resolved_db)
    conn = sqlite3.connect(str(resolved_db))
    try:
        cursor = conn.cursor()
        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            INSERT OR REPLACE INTO backtest_audits (
                ticker, recommendation_date, audit_date, days_elapsed,
                initial_price, end_price, raw_return, reflection, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker,
            recommendation_date,
            audit_date,
            days_elapsed,
            initial_price,
            end_price,
            raw_return,
            reflection,
            created_at
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to save backtest audit to SQLite: {e}")
    finally:
        conn.close()


def query_backtest_audits(
    results_dir: str | Path,
    ticker: Optional[str] = None,
    limit: int = 100,
    db_path: Optional[str | Path] = None
) -> List[Dict[str, Any]]:
    """Retrieve backtest audits from SQLite."""
    resolved_db = _resolve_db(results_dir, db_path)
    init_db(resolved_db)
    conn = sqlite3.connect(str(resolved_db))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM backtest_audits WHERE 1=1"
        params: List[Any] = []
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)
            
        query += " ORDER BY recommendation_date DESC, days_elapsed ASC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to query backtest audits from SQLite: {e}")
        return []
    finally:
        conn.close()


