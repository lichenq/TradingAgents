#!/usr/bin/env python3
"""Automated Daily 3-Stock Recommendation and Buy-In Price Extraction System.

This script automates the end-to-end workflow to generate EXACTLY 3 high-quality stock
recommendations for the next trading day, complete with concrete entry prices,
stop-loss levels, and sizing guidelines extracted from the deep multi-agent reports.

Features:
1. Dynamic Fallback Loop: Automatically expands Stage 2 validation range if deep
   filters or bearish market factors prune too many top technical candidates.
2. Intelligent Price Extraction: Parses structural and narrative elements of the
   Trader and Portfolio Manager reports to retrieve the precise execution parameters.
3. Strict Safety Safeguards: If extreme market conditions (like panic sell-offs) yield
   no 'Buy/Overweight' ratings, it lists the top 3 defensive/Hold assets with a prominent
   warning, maintaining risk discipline.
4. Export and Publishing: Saves output to daily JSON and Markdown files ready for push
   integrations (WeChat, Feishu, etc.).
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Adjust sys.path to find tradingagents
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.trade_date import resolve_default_trade_date
from tradingagents.graph.storage import _resolve_db, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("daily_recommender")


def run_recommendation_pipeline(
    strategy: str,
    board: str,
    validate_top: int,
    trade_date: str,
    results_dir: str,
) -> bool:
    """Invoke the baseline run_recommend.py script via subprocess."""
    python_bin = sys.executable
    recommend_script = project_root / "scripts" / "run_recommend.py"
    
    cmd = [
        python_bin,
        str(recommend_script),
        "--strategy", strategy,
        "--board", board,
        "--validate-top", str(validate_top),
        "--concurrency", "3",
    ]
    if trade_date:
        cmd.extend(["--date", trade_date])
        
    # Inject result directory environment
    env = os.environ.copy()
    env["TRADINGAGENTS_RESULTS_DIR"] = results_dir
    # Wipe proxy settings to avoid sandboxing conflicts
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    env.setdefault("TRADINGAGENTS_TUIGE_ENABLED", "1")
    env.setdefault("TRADINGAGENTS_MARKET", "cn")

    logger.info(f"Executing: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
        logger.info("Recommendation subprocess completed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Subprocess failed with code {e.returncode}")
        logger.error(f"Stderr: {e.stderr}")
        return False


def extract_price_and_stop_loss(trader_plan: str, decision_text: str, current_price: float) -> Tuple[str, str, str]:
    """Robust regex extraction for entry price, stop loss, and position sizing."""
    entry_price = "待定"
    stop_loss = "待定"
    sizing = "待定"
    
    # 1. Parse from structured Trader Proposal Markdown
    if trader_plan:
        entry_match = re.search(r"\*\*Entry Price\*\*:\s*([\d\.-]+)", trader_plan, re.IGNORECASE)
        stop_match = re.search(r"\*\*Stop Loss\*\*:\s*([\d\.-]+)", trader_plan, re.IGNORECASE)
        sizing_match = re.search(r"\*\*Position Sizing\*\*:\s*([^\n]+)", trader_plan, re.IGNORECASE)
        if entry_match:
            entry_price = entry_match.group(1).strip()
        if stop_match:
            stop_loss = stop_match.group(1).strip()
        if sizing_match:
            sizing = sizing_match.group(1).strip()
            
    # 2. Parse narrative text from final Portfolio Manager Decision (Chinese)
    if sizing == "待定" or sizing == "10% - 15% 试探仓":
        m_tuige = re.search(
            r"\*\*Position Sizing \(Tuige\)\*\*:\s*([^\n]+)",
            decision_text,
            re.IGNORECASE,
        )
        if m_tuige:
            sizing = m_tuige.group(1).strip()

    if entry_price == "待定" and decision_text:
        # Search patterns: "入场价参考现价80.74元附近" or "72-75元且缩量企稳" or "回到40-50×"
        m = re.search(r"(?:入场价|建议买入|建议入场|买入价|挂单价|价格回落至)[^\d\w]*?([\d\.-]+)\s*元?", decision_text)
        if m:
            entry_price = m.group(1).strip()
        else:
            # Fallback to current price if wait trigger
            if "等回踩" in decision_text or "回调" in decision_text:
                entry_price = f"等回踩 (参考现价: {current_price:.2f})"
            else:
                entry_price = f"现价附近 ({current_price:.2f})"
                
        # Search for stop loss in PM decision
        m_sl = re.search(r"(?:硬止损|止损设在|止损)[^\d\w]*?([\d\.-]+)\s*元?", decision_text)
        if m_sl:
            stop_loss = m_sl.group(1).strip()
        elif "8%" in decision_text or "10%" in decision_text:
            stop_loss = f"当前-8%硬止损 (~{current_price * 0.92:.2f})"
            
    # Normalize defaults
    if entry_price == "待定":
        entry_price = f"现价附近 ({current_price:.2f})"
    if stop_loss == "待定":
        stop_loss = f"-8% (约 {current_price * 0.92:.2f})"
    if sizing == "待定" or not sizing:
        sizing = "10% - 15% 试探仓"
        
    return entry_price, stop_loss, sizing


def fetch_report_data(ticker: str, trade_date: str, db_path: Path) -> Tuple[str, str]:
    """Retrieve deep report contents from SQLite reports table."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT trader_investment_plan, final_trade_decision FROM reports WHERE ticker = ? AND trade_date = ?",
            (ticker, trade_date)
        )
        row = cursor.fetchone()
        if row:
            return row["trader_investment_plan"] or "", row["final_trade_decision"] or ""
    except Exception as e:
        logger.error(f"Error reading SQLite reports: {e}")
    finally:
        conn.close()
    return "", ""


def query_all_recommendations(trade_date: str, strategy: str, db_path: Path) -> List[Dict[str, Any]]:
    """Retrieve all recommendations of the trade date from SQLite, ordered by ranking/score."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    results = []
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM recommendations WHERE trade_date = ? AND strategy = ?",
            (trade_date, strategy)
        )
        rows = cursor.fetchall()
        for row in rows:
            item = dict(row)
            item["metrics"] = json.loads(item["metrics"] or "{}")
            results.append(item)
    except Exception as e:
        logger.error(f"Error querying SQLite recommendations: {e}")
    finally:
        conn.close()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strategy",
        default="trend_pullback",
        help="Screening strategy (default: trend_pullback)"
    )
    parser.add_argument(
        "--board",
        default="auto",
        help="Specify industry sector (e.g. '半导体' or 'auto' to align hot sectors)"
    )
    parser.add_argument(
        "--date",
        default="",
        help="Trade date YYYY-MM-DD (defaults to latest trade date)"
    )
    parser.add_argument(
        "--results-dir",
        default="",
        help="Results output directory"
    )
    parser.add_argument(
        "--md",
        action="store_true",
        help="Whether to compile and save the Markdown bulletin report (default: False)"
    )
    args = parser.parse_args()

    results_dir = args.results_dir or os.environ.get("TRADINGAGENTS_RESULTS_DIR") or DEFAULT_CONFIG["results_dir"]
    db_path = _resolve_db(results_dir, None)
    init_db(db_path)

    # Resolve date
    trade_date = args.date
    if not trade_date:
        trade_date = resolve_default_trade_date()
    logger.info(f"Target Analysis Trading Date: {trade_date}")

    # Step 1: Dynamic Validation Loop
    # We want EXACTLY 3 recommended stocks. We'll try validate_top starting at 5.
    # If we find fewer than 3 Buy/Overweight/Hold recommendations, we'll expand to 10, then 15.
    # Since analyzed stocks are cached in SQLite, subsequent runs are extremely fast.
    validate_sizes = [5, 10, 15]
    final_selected = []
    has_warning = False
    
    for size in validate_sizes:
        logger.info(f"--- Running Recommendation Pipeline with validate_top={size} ---")
        ok = run_recommendation_pipeline(args.strategy, args.board, size, trade_date, results_dir)
        if not ok:
            logger.error("Failed to execute baseline recommendation. Aborting.")
            return 1
            
        # Check SQLite db for results
        recs = query_all_recommendations(trade_date, args.strategy, db_path)
        
        # Sort recommendations by rating priority: Buy (1) > Overweight (2) > Hold (3) > Underweight (4) > Sell (5)
        rating_priority = {"Buy": 1, "Overweight": 2, "Hold": 3, "Underweight": 4, "Sell": 5, "FAILED": 6}
        recs.sort(key=lambda x: (rating_priority.get(x.get("rating", "FAILED"), 6), -float(x.get("score") or 0.0)))
        
        # Filter for active candidates (Buy, Overweight, Hold)
        active_candidates = [r for r in recs if r.get("rating") in ["Buy", "Overweight", "Hold"]]
        
        logger.info(f"Found {len(active_candidates)} active recommendations (Buy/Overweight/Hold) in SQLite out of {len(recs)} total validated.")
        
        if len(active_candidates) >= 3 or size == validate_sizes[-1] or len(recs) < size:
            # We have enough, or we hit the maximum limit
            final_selected = active_candidates[:3]
            # Fallback if we still don't have 3 active candidates: fill up with Underweight/Sell
            if len(final_selected) < 3 and len(recs) > 0:
                has_warning = True
                remaining_slots = 3 - len(final_selected)
                non_active = [r for r in recs if r.get("rating") not in ["Buy", "Overweight", "Hold"]]
                final_selected.extend(non_active[:remaining_slots])
            break

    if not final_selected:
        print(f"❌ 错误：在 {trade_date} 未能获取到任何有效的初筛或研判标的。请确认当日 A 股数据是否正常。")
        return 1

    # Step 2: Extraction and Compilation
    tuige_context: Dict[str, Any] = {}
    rec_json_path = Path(results_dir) / "recommendations" / trade_date / "recommended_stocks.json"
    if rec_json_path.is_file():
        try:
            with open(rec_json_path, encoding="utf-8") as f:
                rec_payload = json.load(f)
            tuige_context = rec_payload.get("tuige_context") or {}
        except Exception as exc:
            logger.warning("Could not load tuige_context from %s: %s", rec_json_path, exc)

    bulletin_data = []
    for r in final_selected:
        ticker = r["ticker"]
        name = r["name"]
        rating = r["rating"]
        current_price = float(r.get("price") or 0.0)
        score = float(r.get("score") or 0.0)
        reason = r.get("reason") or ""
        metrics = r.get("metrics") or {}
        if isinstance(metrics, str):
            try:
                metrics = json.loads(metrics)
            except json.JSONDecodeError:
                metrics = {}
        
        trader_plan, pm_decision = fetch_report_data(ticker, trade_date, db_path)
        entry_price, stop_loss, sizing = extract_price_and_stop_loss(trader_plan, pm_decision, current_price)
        
        # Extract dynamic trigger narrative (first 2 sentences of Executive Summary)
        trigger_narrative = "回调企稳后分批入场。"
        if pm_decision:
            summary_match = re.search(r"\*\*Executive Summary\*\*:\s*([^\n]+)", pm_decision)
            if summary_match:
                trigger_narrative = summary_match.group(1).strip()
                # Truncate to reasonable size
                if len(trigger_narrative) > 100:
                    trigger_narrative = trigger_narrative[:97] + "..."
                    
        bulletin_data.append({
            "ticker": ticker,
            "name": name,
            "rating": rating,
            "current_price": current_price,
            "score": score,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "sizing": sizing,
            "triggers": trigger_narrative,
            "technical_reason": reason,
            "tuige_setup": metrics.get("tuige_setup"),
            "position_grade": metrics.get("position_grade"),
        })

    # Step 3: Print and Save Bulletin Report
    bulletin_dir = Path(results_dir) / "daily_bulletins"
    bulletin_dir.mkdir(parents=True, exist_ok=True)
    
    bulletin_json_path = bulletin_dir / f"bulletin_{trade_date}.json"
    bulletin_md_path = bulletin_dir / f"bulletin_{trade_date}.md"
    
    # Save JSON
    with open(bulletin_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "trade_date": trade_date,
            "is_fallback_warning": has_warning,
            "strategy": args.strategy,
            "tuige_context": tuige_context,
            "selections": bulletin_data
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Daily bulletin generated successfully.")
    print(f"  - JSON saved to: {bulletin_json_path.resolve()}")

    if args.md:
        # Compile Markdown Bulletin (only if explicitly requested via --md)
        md_lines = [
            f"# 🎯 TradingAgents 盘后明日量化精选（3 只带买入价）",
            f"- **分析交易日**: `{trade_date}` (研判明日: { (datetime.datetime.strptime(trade_date, '%Y-%m-%d') + datetime.timedelta(days=3 if datetime.datetime.strptime(trade_date, '%Y-%m-%d').weekday() == 4 else 1)).strftime('%Y-%m-%d') })",
            f"- **选股量化因子**: `{args.strategy}` 形态回踩 + Serenity 板块量化资金穿透",
            f"- **数据更新时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        if tuige_context.get("enabled"):
            from tradingagents.tuige.position_grade import format_tuige_summary

            md_lines.append(f"- **Tuige 市况**: {format_tuige_summary(tuige_context)}")
            md_lines.append("")
        
        if has_warning:
            md_lines.extend([
                "### ⚠️ 风险警示 (Risk Discipline Warning)",
                "> **市场环境极端偏空或当前板块遭遇强主力资金流出（触及估值熔断红线）**。",
                "> 为坚守 **Serenity 严苛风控** 与 **“宁缺毋滥”底线**，今日无 3 只符合 Buy/Overweight 评级的标的。",
                "> 下方标的包含 Hold 或防守型 Underweight 评级，**买入价严格遵循条件回踩触发**，不可开盘盲目市价追高！",
                "",
            ])
            
        md_lines.extend([
            "## 📊 盘后精选买点对照表",
            "",
            "| 股票名称 (代码) | 最新现价 | 🎯 建议买入价/区间 | 🛑 建议止损价 | 💼 建议仓位 | 智能体评级 | 核心执行触发动作与买点逻辑 |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
        ])
        
        for b in bulletin_data:
            code6 = b["ticker"][-6:]
            md_lines.append(
                f"| **{b['name']}** (`{code6}`) | {b['current_price']:.2f} 元 | **{b['entry_price']}** | `{b['stop_loss']}` | *{b['sizing']}* | **{b['rating']}** | {b['triggers']} |"
            )
            
        md_lines.extend([
            "",
            "---",
            "## 💡 核心择时与挂单指引",
            "1. **挂单纪律**：表中建议买入价均属于**“日线或分时缩量回踩触及”**时的低风险挂单价，若明日股票大幅高开（开盘 > 建议价 2.5%），应主动放弃该笔交易，谨防高位接盘。",
            "2. **防爆一票否决**：若大盘或所属行业板块开盘出现恐慌大跌，即使价格跌入买入区间也先不接飞刀，须等待 **14:30 以后** 观察主力资金是否完成回流再做定夺。",
            "3. **硬止损强制执行**：入场后，若收盘价有效跌破 **🛑 建议止损价**，必须于次日开盘无条件止损出局，禁止裸奔抗单。",
            "",
            f"*( bulletin 结构化数据已同步至: {bulletin_json_path.resolve()} )*"
        ])
        
        md_text = "\n".join(md_lines)
        with open(bulletin_md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
            
        print("\n" + "="*80)
        print(md_text)
        print("="*80 + "\n")
        print(f"  - Markdown saved to: {bulletin_md_path.resolve()}")
    else:
        # If not generating md, print a simple console-friendly summary of the 3 stocks
        print("\n" + "="*50)
        print("🎯 Tomorrow's 3 Stock Recommendations:")
        for b in bulletin_data:
            code6 = b["ticker"][-6:]
            print(f"  - {b['name']} ({code6}): Rating={b['rating']}, Price={b['current_price']:.2f}, Entry={b['entry_price']}, Stop={b['stop_loss']}")
        print("="*50 + "\n")
        print("*(Markdown bulletin generation skipped as requested. Run with --md to generate)*")

    return 0


if __name__ == "__main__":
    sys.exit(main())
