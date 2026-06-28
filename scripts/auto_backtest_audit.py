#!/usr/bin/env python3
"""Automated Backtest, Post-Audit, and AI Reflection Loop for TradingAgents.

This script runs daily (typically after market close):
1. Reads past recommended stock selections from SQLite database (e.g. 3-5 days ago).
2. Fetches the actual current close price using free realtime quote APIs.
3. Computes the real return of the recommendations since they were proposed.
4. Feeds underperforming or outperforming cases to an AI Reflection Agent to form
   learning insights.
5. Saves results and AI reflections in the SQLite `backtest_audits` table.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Adjust sys.path to find tradingagents
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.a_share_runner import run_script
from tradingagents.dataflows.audit_failure_modes import (
    classify_failure_modes,
    fetch_pe_ttm,
)
from tradingagents.dataflows.audit_report import write_audit_report
from tradingagents.dataflows.trade_date import cn_trading_sessions_after
from tradingagents.graph.storage import get_db_path, init_db, query_report, save_backtest_audit
from tradingagents.llm_clients import create_llm_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("backtest_audit")


def fetch_latest_price(code6: str) -> Optional[float]:
    """Fetch the latest real-time close price for an A-share ticker."""
    ok, raw, data = run_script(
        "fetch_realtime.py",
        ["--quote", code6, "--json"],
        timeout=25,
    )
    if ok and isinstance(data, dict):
        price = data.get("最新价") or data.get("price")
        if price is not None:
            return float(price)
    return None


def get_recommendations_to_audit(
    conn: sqlite3.Connection,
    audit_days: int,
    as_of: Optional[datetime.date] = None,
) -> List[Dict[str, Any]]:
    """Query recommendations ready for audit at the given trading-session horizon."""
    as_of = as_of or datetime.date.today()
    logger.info(
        f"Searching for recommendations with >={audit_days} trading sessions elapsed "
        f"(as_of={as_of.isoformat()})"
    )

    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT r.* FROM recommendations r
        LEFT JOIN backtest_audits b
          ON r.code = b.ticker
         AND r.trade_date = b.recommendation_date
         AND b.days_elapsed = ?
        WHERE b.id IS NULL
          AND COALESCE(r.is_final, 0) = 1
          AND r.rating IN ('Buy', 'Overweight')
    """, (audit_days,))

    rows = [dict(row) for row in cursor.fetchall()]
    ready = [
        r for r in rows
        if cn_trading_sessions_after(r["trade_date"], as_of) >= audit_days
    ]
    if rows and not ready:
        logger.info(
            f"{len(rows)} unaudited recommendation(s) found but none reached "
            f"{audit_days} trading sessions yet."
        )
    return ready


def run_ai_reflection_agent(
    ticker: str,
    trade_date: str,
    initial_price: float,
    current_price: float,
    total_return: float,
    quant_reason: str,
    deep_decision_report: Optional[str] = None
) -> str:
    """Trigger an LLM-powered reflection agent to analyze the decision outcome and extract trade lessons."""
    logger.info(f"Running AI Reflection Agent for {ticker}...")
    
    provider = DEFAULT_CONFIG["llm_provider"]
    model = DEFAULT_CONFIG["quick_think_llm"]
    base_url = DEFAULT_CONFIG.get("backend_url")
    
    llm_client = create_llm_client(provider=provider, model=model, base_url=base_url)
    llm = llm_client.get_llm()
    
    system_prompt = (
        "You are an expert AI Quant Post-Audit Analyst and Trading Reflector.\n"
        "Your task is to retrospectively analyze a previous stock recommendation now that the actual price outcome is known.\n"
        "You must generate a concise, objective, and evidence-backed reflection (exactly 3-5 sentences of plain prose, no bullet points, no headers, no markdown bolding).\n"
        "Be extremely direct. Address:\n"
        "1. Directional Accuracy: Was the original multi-agent rating (Buy/Hold/Sell) correct given the actual return? (cite exact numbers)\n"
        "2. Core Thesis Audit: Which key factors from the technical momentum or deep multi-agent report correctly predicted or failed to anticipate the trend? (cite specific metrics like PE, RSI, popularity ranking changes)\n"
        "3. Explicit Learning Takeaway: State one actionable rule to adjust Stage 1 parameters, Stage 2 debate criteria, or risk margins next time."
    )
    
    user_prompt = (
        f"Ticker Symbol: {ticker}\n"
        f"Recommendation Date: {trade_date}\n"
        f"Recommendation Price: {initial_price:.2f} CNY\n"
        f"Current Price (After Backtest Horizon): {current_price:.2f} CNY\n"
        f"Actual Cumulative Return: {total_return:+.2%}\n\n"
        f"Stage 1 Quant Selection Reason:\n{quant_reason}\n\n"
    )
    
    if deep_decision_report:
        user_prompt += f"Stage 2 Deep Multi-Agent Report & Consensus (Truncated):\n{deep_decision_report[:1200]}\n"
    else:
        user_prompt += "Stage 2 Deep Multi-Agent Report: Not available.\n"
        
    try:
        messages = [
            ("system", system_prompt),
            ("human", user_prompt)
        ]
        response = llm.invoke(messages)
        reflection_text = str(response.content).strip()
        logger.info("AI Reflection successfully completed.")
        return reflection_text
    except Exception as e:
        logger.error(f"Failed to invoke AI Reflection LLM: {e}")
        return "AI Reflection failed due to API connection error."


def main() -> int:
    parser = argparse.ArgumentParser(description="Automated Backtest and AI Reflection Loop")
    parser.add_argument(
        "--days-ago",
        type=int,
        default=3,
        help="Audit recommendations made N days ago (default: 3)"
    )
    parser.add_argument(
        "--results-dir",
        default="",
        help="Custom results directory containing the SQLite database"
    )
    parser.add_argument(
        "--as-of",
        default="",
        help="Audit as-of date YYYY-MM-DD (default: today)"
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write audit KPI report JSON after audit cycle"
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir) if args.results_dir else Path(DEFAULT_CONFIG["results_dir"])
    as_of = (
        datetime.datetime.strptime(args.as_of[:10], "%Y-%m-%d").date()
        if args.as_of.strip()
        else datetime.date.today()
    )
    db_path = get_db_path(results_dir)
    init_db(results_dir)
    
    logger.info(f"Opening SQLite database at: {db_path}")
    conn = sqlite3.connect(str(db_path))
    
    try:
        recs = get_recommendations_to_audit(conn, args.days_ago, as_of=as_of)
        if not recs:
            logger.info(
                f"No unaudited recommendations ready for {args.days_ago}-session horizon. "
                "Everything is up to date!"
            )
            if args.write_report:
                path = write_audit_report(results_dir, as_of=as_of)
                logger.info(f"Audit KPI report written: {path}")
            return 0
            
        logger.info(f"Found {len(recs)} recommendation(s) to audit.")
        
        for r in recs:
            code = r["code"]
            name = r["name"]
            trade_date = r["trade_date"]
            initial_price = r["price"]
            quant_reason = r["reason"]
            code6 = code[-6:]
            
            logger.info(f"Auditing {name} ({code6}) recommended on {trade_date} at {initial_price} CNY...")
            
            # 1. Fetch current price
            current_price = fetch_latest_price(code6)
            if current_price is None:
                logger.error(f"Cannot fetch current price for {code6}. Skipping audit for this ticker.")
                continue
                
            # 2. Calculate return
            total_return = (current_price - initial_price) / initial_price
            logger.info(f"Backtest Outcome: Initial={initial_price:.2f} CNY, Current={current_price:.2f} CNY, Return={total_return:+.2%}")

            pe_ttm = fetch_pe_ttm(code, trade_date, DEFAULT_CONFIG)
            failure_modes = classify_failure_modes(
                r, total_return, pe_ttm=pe_ttm
            )
            if failure_modes:
                logger.info(f"Failure modes: {', '.join(failure_modes)}")
            
            # 3. Pull deep report if it exists
            deep_report_text = None
            try:
                report_data = query_report(results_dir, code, trade_date)
                if report_data:
                    deep_report_text = report_data.get("complete_report")
            except Exception as e:
                logger.warning(f"Could not retrieve deep report for {code} on {trade_date} from SQLite: {e}")
                
            # 4. Invoke AI Reflection Agent
            reflection = run_ai_reflection_agent(
                ticker=code,
                trade_date=trade_date,
                initial_price=initial_price,
                current_price=current_price,
                total_return=total_return,
                quant_reason=quant_reason,
                deep_decision_report=deep_report_text
            )
            
            # 5. Save back to SQLite backtest_audits
            audit_date = as_of.strftime("%Y-%m-%d")
            save_backtest_audit(
                results_dir=results_dir,
                ticker=code,
                recommendation_date=trade_date,
                audit_date=audit_date,
                days_elapsed=args.days_ago,
                initial_price=initial_price,
                end_price=current_price,
                raw_return=total_return,
                reflection=reflection,
                failure_modes=failure_modes,
            )
            logger.info(f"Audit saved to SQLite backtest_audits for {name} ({code6}). Reflection: {reflection[:80]}...\n")
            
            # 6. Optionally write reflection to a central reflection ledger file
            try:
                ledger_path = results_dir / "reflection_ledger.md"
                ledger_exists = ledger_path.is_file()
                with open(ledger_path, "a", encoding="utf-8") as f:
                    if not ledger_exists:
                        f.write("# 📑 TradingAgents AI Multi-Agent Post-Audit Reflection Ledger\n\n")
                    f.write(f"## 🔍 Ticker: {name} ({code6}) | Rec Date: {trade_date} | Audit Date: {audit_date}\n")
                    f.write(f"- **Initial Price**: {initial_price:.2f} CNY\n")
                    f.write(f"- **Current Price**: {current_price:.2f} CNY\n")
                    f.write(f"- **Backtest Horizon**: {args.days_ago} days\n")
                    f.write(f"- **Return**: {total_return:+.2%}\n")
                    if failure_modes:
                        f.write(f"- **Failure Modes**: {', '.join(failure_modes)}\n")
                    f.write(f"- **AI Quant/Risk Reflection Insights**:\n  > {reflection}\n\n")
                logger.info(f"Appended reflection insights to: {ledger_path}")
            except Exception as e:
                logger.error(f"Failed to append reflection insights to ledger file: {e}")
                
    except Exception as e:
        logger.error(f"Critical error during automated audit: {e}", exc_info=True)
        return 1
    finally:
        conn.close()

    if args.write_report:
        try:
            path = write_audit_report(results_dir, as_of=as_of)
            logger.info(f"Audit KPI report written: {path}")
        except Exception as e:
            logger.error(f"Failed to write audit KPI report: {e}")

    logger.info("Automated Backtest and AI Reflection Audit cycle successfully completed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
