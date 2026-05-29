#!/usr/bin/env python3
"""Non-interactive stock recommendation system for TradingAgents (Stage 1 Screener + Stage 2 Deep Validation)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

# Monkeypatch concurrent.futures.process._check_system_limits to bypass PermissionError in macOS sandbox
try:
    import concurrent.futures.process
    concurrent.futures.process._check_system_limits = lambda: None
except Exception:
    pass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

# Adjust path to find tradingagents
from tradingagents.dataflows.report_paths import report_bundle_dir
from tradingagents.dataflows.trade_date import resolve_default_trade_date
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.graph.storage import (
    build_report_storage_ref,
    init_db,
    query_deep_report,
)
from tradingagents.agents.utils.rating import parse_rating
from tradingagents.dataflows.a_share_runner import run_script

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("recommender")

# Constants
SUPPORTED_STRATEGIES = ["trend_pullback", "macd_resonance", "macd_second_golden_cross", "em_hot_momentum", "em_fomo_exit"]


def recommend_progress_enabled() -> bool:
    """Default on; set TRADINGAGENTS_RECOMMEND_PROGRESS=0 to disable."""
    raw = os.environ.get("TRADINGAGENTS_RECOMMEND_PROGRESS", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


class RecommendProgress:
    """Stage-level progress + elapsed time (stderr), similar to analyze propagate logs."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._pipeline_start = time.perf_counter()
        self._stages: List[Tuple[str, float, str]] = []
        self._current_label: Optional[str] = None
        self._stage_start = 0.0

    def _emit(self, msg: str) -> None:
        if self.enabled:
            logger.info(msg)

    def step(self, msg: str) -> None:
        self._emit(f"[recommend]   · {msg}")

    def begin(self, label: str) -> None:
        if self._current_label is not None:
            self._finish_current()
        self._current_label = label
        self._stage_start = time.perf_counter()
        self._emit(f"[recommend] ▶ {label} ...")

    def _finish_current(self, detail: str = "") -> None:
        if self._current_label is None:
            return
        elapsed = time.perf_counter() - self._stage_start
        self._stages.append((self._current_label, elapsed, detail))
        suffix = f" — {detail}" if detail else ""
        self._emit(f"[recommend] ✓ {self._current_label} {elapsed:.1f}s{suffix}")
        self._current_label = None

    def end(self, detail: str = "") -> None:
        self._finish_current(detail)

    @contextmanager
    def stage(self, label: str, detail: Callable[[], str] | None = None):
        self.begin(label)
        try:
            yield
        finally:
            d = detail() if detail else ""
            self.end(d)

    def finish_pipeline(self) -> None:
        if self._current_label is not None:
            self._finish_current()
        if not self.enabled:
            return
        total = time.perf_counter() - self._pipeline_start
        self._emit("[recommend] " + "=" * 56)
        self._emit("[recommend] 环节耗时汇总")
        for label, elapsed, detail in self._stages:
            extra = f" ({detail})" if detail else ""
            self._emit(f"[recommend]   {label:<30} {elapsed:>7.1f}s{extra}")
        self._emit(f"[recommend]   {'合计':<30} {total:>7.1f}s")
        self._emit("[recommend] " + "=" * 56)


def run_a_share_script(script: str, args: List[str], timeout: int = 45) -> tuple[bool, str, Optional[Any]]:
    """Safe wrapper to execute a-share-data scripts via the project's runner."""
    return run_script(script, args, timeout=timeout)


# =====================================================================
# STAGE 1: Technical Indicators Calculations
# =====================================================================

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate moving averages, MACD, and RSI on a K-line DataFrame."""
    df = df.sort_values("time").copy()
    if len(df) < 5:
        return df

    # MAs
    df["MA5"] = df["close"].rolling(5).mean()
    df["MA10"] = df["close"].rolling(10).mean()
    df["MA20"] = df["close"].rolling(20).mean()
    df["MA30"] = df["close"].rolling(30).mean()
    df["MA50"] = df["close"].rolling(50).mean()
    df["MA60"] = df["close"].rolling(60).mean()

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD_DIF"] = ema12 - ema26
    df["MACD_DEA"] = df["MACD_DIF"].ewm(span=9, adjust=False).mean()
    df["MACD"] = 2 * (df["MACD_DIF"] - df["MACD_DEA"])

    # RSI 14
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=14).mean()
    rs = gain / loss.replace(0.0, np.nan)
    df["RSI14"] = 100 - (100 / (1 + rs))
    df["RSI14"] = df["RSI14"].fillna(50.0)

    return df


# =====================================================================
# STAGE 1: Screening Strategies
# =====================================================================

def screen_trend_pullback(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Strategy 1: Trend Pullback (趋势回踩)."""
    if len(df) < 35:
        return None
    last = df.iloc[-1]
    
    ma10, ma30 = last["MA10"], last["MA30"]
    rsi = last["RSI14"]
    close = last["close"]

    if pd.isna(ma10) or pd.isna(ma30) or pd.isna(rsi):
        return None

    # Conditions:
    # 1. MA10 > MA30 (Strong uptrend)
    # 2. close > MA30 (Above long-term line)
    # 3. close < MA10 * 1.015 (Pullback near MA10)
    # 4. RSI between 40 and 68 (Not overbought or oversold)
    cond1 = ma10 > ma30
    cond2 = close > ma30
    cond3 = close < ma10 * 1.015
    cond4 = 40 <= rsi <= 68

    if cond1 and cond2 and cond3 and cond4:
        score = float((ma10 / ma30 - 1.0) * 100)
        return {
            "score": score,
            "metrics": {
                "close": float(close),
                "ma10": float(ma10),
                "ma30": float(ma30),
                "rsi14": float(rsi)
            },
            "reason": f"日线均线 MA10({ma10:.2f}) > MA30({ma30:.2f}) 处于上升趋势，价格回踩至 {close:.2f} 附近，RSI({rsi:.1f}) 处于健康区间。"
        }
    return None


def screen_macd_resonance(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Strategy 2: MACD Trend Resonance (均线共振)."""
    if len(df) < 62:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]

    close = last["close"]
    ma20, ma60 = last["MA20"], last["MA60"]
    ma60_prev = prev["MA60"]
    dif, dea, macd = last["MACD_DIF"], last["MACD_DEA"], last["MACD"]
    dif_prev, dea_prev = prev["MACD_DIF"], prev["MACD_DEA"]
    macd_prev = prev["MACD"]

    if any(pd.isna(x) for x in [ma20, ma60, ma60_prev, dif, dea, macd]):
        return None

    # Hard Filters
    # 1. MA60 must be rising
    # 2. Price must be above MA60
    # 3. DIF > DEA
    if not (ma60 > ma60_prev and close > ma60 and dif > dea):
        return None

    # Scoring System
    t_score = 20  # Base for rising MA60
    if close > ma60:
        t_score += 10
    if ma20 > ma60:
        t_score += 10

    m_score = 0
    if dif > 0 and dea > 0:
        m_score += 15  # Water-above
    
    # Golden cross check
    if dif > dea and dif_prev <= dea_prev:
        m_score += 10
    else:
        m_score += 5

    if macd > macd_prev and macd > 0:
        m_score += 5

    score = t_score + m_score
    return {
        "score": float(score),
        "metrics": {
            "close": float(close),
            "ma20": float(ma20),
            "ma60": float(ma60),
            "dif": float(dif),
            "dea": float(dea),
            "macd": float(macd)
        },
        "reason": f"均线多头共振。60日均线向上，价格站稳 MA60 零上，MACD金叉或多头运行，日线趋势共振得分 {score} 分。"
    }


def screen_macd_second_golden_cross(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Strategy 3: MACD Bottom Divergence + Water-under Second Golden Cross (水下二次金叉底背离)."""
    if len(df) < 65:
        return None

    # We inspect the last 60 bars to find two consecutive water-under golden crosses
    dif = df["MACD_DIF"].values
    dea = df["MACD_DEA"].values
    close_vals = df["close"].values
    times = df["time"].values

    # Detect golden crosses (DIF crosses above DEA)
    gcs = []
    for i in range(len(df) - 60, len(df)):
        if i <= 0:
            continue
        if dif[i] > dea[i] and dif[i-1] <= dea[i-1]:
            # Must be water-under (DIF < 0 and DEA < 0)
            if dif[i] < 0 and dea[i] < 0:
                gcs.append(i)

    if len(gcs) < 2:
        return None

    # Let's check the latest golden cross (GC2)
    gc2_idx = gcs[-1]
    # GC2 must be very recent (within last 8 days)
    if (len(df) - 1 - gc2_idx) > 8:
        return None

    # Find the previous golden cross (GC1) within 10 to 50 days of GC2
    gc1_idx = None
    for idx in reversed(gcs[:-1]):
        dist = gc2_idx - idx
        if 8 <= dist <= 50:
            gc1_idx = idx
            break

    if gc1_idx is None:
        return None

    # Divergence criteria:
    # 1. Price at GC2 is lower than or very close to price at GC1
    # 2. DIF value at GC2 is significantly higher (less negative) than DIF value at GC1
    price_gc1, price_gc2 = close_vals[gc1_idx], close_vals[gc2_idx]
    dif_gc1, dif_gc2 = dif[gc1_idx], dif[gc2_idx]

    # Price should have made a lower or similar bottom, but DIF is higher (bullish divergence)
    is_divergence = (price_gc2 <= price_gc1 * 1.05) and (dif_gc2 > dif_gc1 + 0.01)

    if is_divergence:
        # Score based on how strong the divergence is
        score = float((dif_gc2 - dif_gc1) / abs(dif_gc1) * 100)
        return {
            "score": score,
            "metrics": {
                "close_gc1": float(price_gc1),
                "close_gc2": float(price_gc2),
                "dif_gc1": float(dif_gc1),
                "dif_gc2": float(dif_gc2),
                "gc_distance": gc2_idx - gc1_idx
            },
            "reason": f"出现典型日线底背离与水下二次金叉结构。第一次金叉价格 {price_gc1:.2f} (DIF {dif_gc1:.3f})，第二次金叉价格 {price_gc2:.2f} (DIF {dif_gc2:.3f})，空头力量显著衰竭。"
        }

    return None


def screen_em_hot_momentum(df: pd.DataFrame, sentiment_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Strategy 4: EastMoney Popularity Momentum (东财人气爆棚)."""
    if not sentiment_data or "rank_trend" not in sentiment_data:
        return None
    rank_trend = sentiment_data["rank_trend"]
    if len(rank_trend) < 3:
        return None

    try:
        latest = rank_trend[0]
        oldest = rank_trend[-1]
        
        latest_rank = float(latest.get("排名") or latest.get("rank") or 9999)
        oldest_rank = float(oldest.get("排名") or oldest.get("rank") or 9999)
        new_fans = float(latest.get("新晋粉丝") or latest.get("new_fans") or 0.0)

        # Conditions:
        # 1. Latest popularity rank is inside top 150
        # 2. Rank jumped significantly (e.g. ranked > 600 or rose by at least 300 ranks)
        # 3. New fans (hot money) represents over 52% of visitors
        cond1 = latest_rank <= 150
        cond2 = (oldest_rank > 600) or (oldest_rank - latest_rank >= 300)
        cond3 = new_fans >= 0.52

        if cond1 and cond2 and cond3:
            # Score heavily based on rank and hot money ratio
            score = float((200 - latest_rank) * 0.5 + (oldest_rank - latest_rank) * 0.1 + (new_fans * 100))
            close = float(df.iloc[-1]["close"])
            return {
                "score": score,
                "metrics": {
                    "close": close,
                    "latest_rank": latest_rank,
                    "oldest_rank": oldest_rank,
                    "new_fans": new_fans
                },
                "reason": f"东财人气榜暴增爆发形态。最新人气排名第 {int(latest_rank)} 名（从第 {int(oldest_rank)} 名暴涨），且新晋粉丝占比达 {new_fans * 100:.1f}%，短期散户与热钱极度聚集。"
            }
    except Exception as e:
        logger.warning(f"Error in screen_em_hot_momentum: {e}")
    return None


def screen_em_fomo_exit(df: pd.DataFrame, sentiment_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Strategy 5: EastMoney FOMO Exit Risk Detection (东财情绪退潮避险)."""
    if not sentiment_data or "rank_trend" not in sentiment_data:
        return None
    rank_trend = sentiment_data["rank_trend"]
    if len(rank_trend) < 4:
        return None

    try:
        latest = rank_trend[0]
        # Look back 3-5 days ago
        prev_idx = min(4, len(rank_trend) - 1)
        prev = rank_trend[prev_idx]

        latest_rank = float(latest.get("排名") or latest.get("rank") or 0)
        prev_rank = float(prev.get("排名") or prev.get("rank") or 0)
        
        # Conditions:
        # 1. Popularity is collapsing (rank drops by at least 500 positions)
        # 2. Was popular earlier (prev_rank was inside top 400)
        cond1 = latest_rank - prev_rank >= 500
        cond2 = prev_rank <= 400

        if cond1 and cond2:
            # Higher score means more critical exit signal matching
            score = float((latest_rank - prev_rank) * 0.2 + (latest_rank / 10.0))
            close = float(df.iloc[-1]["close"])
            return {
                "score": score,
                "metrics": {
                    "close": close,
                    "latest_rank": latest_rank,
                    "prev_rank": prev_rank,
                    "rank_drop": latest_rank - prev_rank
                },
                "reason": f"东财情绪高位退潮，触发避险杀跌红线。人气排名 3 天内由第 {int(prev_rank)} 名断崖式暴跌至第 {int(latest_rank)} 名（骤降 {int(latest_rank - prev_rank)} 名），散户踩踏，热度迅速瓦解。"
            }
    except Exception as e:
        logger.warning(f"Error in screen_em_fomo_exit: {e}")
    return None


# =====================================================================
# STAGE 1.5: Fundamental & Regulatory Red Flag Filters
# =====================================================================

def evaluate_fundamental_flags(code: str, allow_loss: bool = False) -> Tuple[bool, str]:
    """Check for fundamental red flags (negative net income, large YoY decrease)."""
    code6 = code[-6:]
    # Fetch financials
    ok, raw, data = run_a_share_script("fetch_history.py", ["--financials", code6, "--json"])
    if not ok or not isinstance(data, list) or not data:
        return False, "Cannot fetch financials data"

    try:
        # Check latest record
        latest = data[0]
        net_profit = latest.get("归属母公司股东的净利润") or latest.get("net_profit") or latest.get("归母净利润")
        profit_yoy = latest.get("净利润同比增长率") or latest.get("net_profit_yoy") or latest.get("归母净利润同比")

        # Fallback to float conversion
        def to_float(val):
            if val is None: return 0.0
            if isinstance(val, (int, float)): return float(val)
            # handle percentages strings e.g. " -20.5%"
            s = str(val).replace("%", "").strip()
            try:
                return float(s)
            except ValueError:
                return 0.0

        np_val = to_float(net_profit)
        yoy_val = to_float(profit_yoy)

        # Flag 1: Net profit is negative (Loss-making company)
        if np_val < 0 and not allow_loss:
            return True, f"最新一期净利润亏损 ({np_val/10000:.2f}万元)"

        # Flag 2: YoY net profit dropped by more than 50%
        if yoy_val < -50.0:
            return True, f"最新一期净利润同比大幅下滑 {yoy_val:.1f}%"

    except Exception as e:
        logger.warning(f"Error checking fundamentals for {code}: {e}")

    return False, ""


def evaluate_regulatory_flags(code: str, name: str) -> Tuple[bool, str]:
    """Check for news or events with regulatory warnings or fraud investigation."""
    code6 = code[-6:]
    ok, raw, events = run_a_share_script("fetch_stock_events.py", ["--code", code6, "--limit", "15", "--json"])
    if not ok or not isinstance(events, list):
        return False, ""

    red_keywords = ["立案调查", "公开谴责", "行政处罚", "爆雷", "监管函", "通报批评", "虚假陈述", "欺诈发行"]
    for ev in events:
        if not isinstance(ev, dict):
            continue
        title = str(ev.get("title") or ev.get("标题") or "").upper()
        content = str(ev.get("content") or ev.get("内容") or ev.get("desc") or "").upper()
        
        for kw in red_keywords:
            if kw in title or kw in content:
                # return true (flagged!) and the reason
                date = ev.get("date") or ev.get("日期") or "近期"
                return True, f"在 {date} 事件中检测到重大监管红线关键词【{kw}】: {title[:40]}"

    return False, ""


def _apply_sqlite_report_to_item(
    item: Dict[str, Any],
    row: Dict[str, Any],
    *,
    code: str,
    trade_date: str,
) -> None:
    """Populate recommend item from reports table (not results/ files)."""
    ftd = row.get("final_trade_decision") or ""
    item["rating"] = parse_rating(ftd)
    item["final_state"] = {
        "final_trade_decision": ftd,
        "investment_plan": row.get("investment_plan") or "",
        "complete_report": row.get("complete_report") or "",
    }
    ref = build_report_storage_ref(code, trade_date)
    item["report_storage"] = ref
    item["report_paths"] = ref
    item["deep_analysis_source"] = "sqlite"
    item["skipped_deep_analysis"] = True


def run_multi_agent_graph(
    item: Dict[str, Any],
    parallel_config: Dict[str, Any],
    trade_date: str,
) -> Dict[str, Any]:
    """Execute deep multi-agent validation, or reuse SQLite reports when present."""
    code = item["code"]
    name = item["name"]
    code6 = code[-6:]
    t0 = time.perf_counter()
    results_dir = parallel_config["results_dir"]
    force = bool(parallel_config.get("recommend_force"))

    if not force:
        row = query_deep_report(results_dir, code, trade_date)
        if row is not None:
            logger.info(f"[recommend]   · 复用 SQLite 深度研判 {name}({code6}) ...")
            _apply_sqlite_report_to_item(item, row, code=code, trade_date=trade_date)
            elapsed = time.perf_counter() - t0
            logger.info(
                f"[recommend]   · 跳过 LLM {name}({code6}) {elapsed:.1f}s → {item['rating']} (sqlite)"
            )
            return item

    logger.info(f"[recommend]   · 开始深度研判 {name}({code6}) ...")
    try:
        local_config = parallel_config.copy()
        bundle = report_bundle_dir(local_config["results_dir"], code, trade_date)
        bundle.mkdir(parents=True, exist_ok=True)
        local_config["memory_log_path"] = str(bundle / "trading_memory.md")

        graph = TradingAgentsGraph(
            selected_analysts=["market", "social", "news", "fundamentals"],
            config=local_config,
            debug=False,
        )
        final_state, decision = graph.propagate(code, trade_date)

        item["rating"] = decision
        item["final_state"] = {
            "final_trade_decision": final_state.get("final_trade_decision") or "",
            "investment_plan": final_state.get("investment_plan") or "",
        }
        ref = build_report_storage_ref(code, trade_date)
        item["report_storage"] = ref
        item["report_paths"] = ref
        item["deep_analysis_source"] = "graph"
        item["skipped_deep_analysis"] = False
        elapsed = time.perf_counter() - t0
        logger.info(f"[recommend]   · 完成 {name}({code6}) {elapsed:.1f}s → {decision}")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        logger.error(f"Failed multi-agent graph run for {name} ({code}): {e}")
        item["rating"] = "FAILED"
        item["error"] = str(e)
        logger.info(f"[recommend]   · 失败 {name}({code6}) {elapsed:.1f}s — {e}")
    return item


# =====================================================================
# Main Recommendation Runner
# =====================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strategy",
        default="trend_pullback",
        choices=SUPPORTED_STRATEGIES,
        help="Screening strategy to use (default: trend_pullback)"
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=120,
        help="Number of stocks to screen in Stage 1 (default: 120)"
    )
    parser.add_argument(
        "--validate-top",
        type=int,
        default=5,
        help="Number of top shortlist candidates to validate deeply via TradingAgents (default: 5)"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Number of parallel TradingAgents graph validation instances (default: 3)"
    )
    parser.add_argument(
        "--date",
        default="",
        help="Trade date YYYY-MM-DD (defaults to latest trade date)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output"
    )
    parser.add_argument(
        "--min-volume-amount",
        type=float,
        default=50000000.0,
        help="Minimum daily volume amount in RMB to filter out illiquid stocks (default: 50,000,000)"
    )
    parser.add_argument(
        "--board",
        default="",
        help="Specify industry sector to screen (e.g. '半导体', '元器件', or 'auto' to auto-align top 5 hot sectors)"
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable stage timing logs on stderr (default: progress on)",
    )
    parser.add_argument(
        "--allow-loss",
        action="store_true",
        help="Allow loss-making companies (negative net income) in candidate selection"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run Stage-2 deep analysis even when SQLite already has a report for that ticker+date",
    )
    args = parser.parse_args()

    if args.concurrency > 3:
        logger.warning(
            f"Requested concurrency {args.concurrency} exceeds safety limit. "
            "Enforcing maximum concurrency of 3 to prevent A-share data site IP bans."
        )
        args.concurrency = 3

    prog = RecommendProgress(enabled=not args.no_progress and recommend_progress_enabled())

    prog._emit("=" * 56)
    prog._emit("STARTING TRADINGAGENTS TWO-STAGE STOCK RECOMMENDATION PIPELINE")
    prog._emit(
        f"Strategy: {args.strategy} | Top-N: {args.top_n} | "
        f"Validate: {args.validate_top} | Concurrency: {args.concurrency}"
    )
    prog._emit("=" * 56)

    # 1. Resolve date
    with prog.stage("解析交易日"):
        config = DEFAULT_CONFIG.copy()
        init_db(config["results_dir"])
        trade_date = args.date.strip() or resolve_default_trade_date("600519", config)
        prog.step(f"trade_date={trade_date}")

    # =====================================================================
    # STAGE 1: Fast Quantitative screening
    # =====================================================================
    with prog.stage("Stage1 全市场行情"):
        ok, raw, quotes_data = run_a_share_script(
            "fetch_realtime.py",
            # top=0 → return full universe (default --top 20 would break board filtering)
            ["--all-quote", "--sort", "amount_desc", "--top", "0", "--json"],
        )
        if not ok or not isinstance(quotes_data, dict):
            logger.error(f"Failed to fetch all stock quotes: {raw}")
            return 1

        quotes_list = quotes_data.get("data", [])
        if not quotes_list:
            logger.error("No quotes returned from a-share data")
            return 1

        meta_total = (quotes_data.get("meta") or {}).get("total")
        prog.step(f"全市场原始行情数={len(quotes_list)}" + (f", meta.total={meta_total}" if meta_total else ""))

        board_codes = set()
        if args.board:
            # Smart Board Name Mapping to align with Eastmoney/DangInvest industry names
            board_aliases = {
                "航天航空": "航空",
                "航空航天": "航空",
                "航天": "航空",
                "电子元件": "元器件",
                "材料行业": "化工原料",
                "材料": "化工原料",
            }
            resolved_board = board_aliases.get(args.board, args.board)
            if resolved_board != args.board:
                prog.step(f"板块名称智能映射: '{args.board}' -> '{resolved_board}'")

            if resolved_board.lower() == "auto":
                prog.step("正在获取今日资金流入前五的热点行业板块...")
                ok_b, raw_b, boards_summary = run_a_share_script(
                    "fetch_realtime.py",
                    ["--boards-summary", "--boards-limit", "5", "--boards-sort", "change_pct_desc", "--json"]
                )
                if ok_b and isinstance(boards_summary, dict):
                    top_boards = [
                        b.get("groupLabel") or b.get("name")
                        for b in boards_summary.get("data", [])
                        if b.get("groupLabel") or b.get("name")
                    ]
                    prog.step(f"今日热点板块前五名: {top_boards}")
                    for board_name in top_boards:
                        ok_c, raw_c, board_detail = run_a_share_script(
                            "fetch_realtime.py",
                            ["--boards-detail", "--boards-group-key", board_name, "--boards-items-limit", "100", "--json"]
                        )
                        if ok_c and isinstance(board_detail, dict):
                            items = (board_detail.get("data") or {}).get("items") or []
                            for item in items:
                                code = item.get("code") or ""
                                code6 = "".join(ch for ch in code if ch.isdigit())[-6:]
                                if len(code6) == 6:
                                    board_codes.add(code6)
                    prog.step(f"自动热点板块对齐完成，共筛选出 {len(board_codes)} 只个股")
                else:
                    logger.warning(f"自动获取热点行业失败: {raw_b}")
            else:
                prog.step(f"正在获取 '{resolved_board}' 板块成分股...")
                ok_c, raw_c, board_detail = run_a_share_script(
                    "fetch_realtime.py",
                    ["--boards-detail", "--boards-group-key", resolved_board, "--boards-items-limit", "300", "--json"]
                )
                if ok_c and isinstance(board_detail, dict):
                    items = (board_detail.get("data") or {}).get("items") or []
                    for item in items:
                        code = item.get("code") or ""
                        code6 = "".join(ch for ch in code if ch.isdigit())[-6:]
                        if len(code6) == 6:
                            board_codes.add(code6)
                    prog.step(f"板块 '{resolved_board}' 共获取到 {len(board_codes)} 只成分股")
                else:
                    logger.warning(f"获取板块 '{resolved_board}' 成分股失败: {raw_c}")

            # If the user specified a board but we got 0 constituents, fail fast with error
            if not board_codes:
                logger.error(f"错误: 无法获取板块 '{resolved_board}' 的任何成分股！请检查板块名称是否正确或拼写。")
                logger.error("常用的板块名称示例: '半导体', '元器件', '电气设备', '通信设备', '航空', '化工原料', '专用机械', '小金属' 等。")
                return 1

            filtered_quotes = [
                q
                for q in quotes_list
                if "".join(ch for ch in q.get("code", "") if ch.isdigit())[-6:] in board_codes
            ]
            prog.step(f"行业过滤: 将全市场 {len(quotes_list)} 只股票过滤至 {len(filtered_quotes)} 只板块成分股")
            quotes_list = filtered_quotes

    # Apply general filters: ST, Price, Amount, Mainboard preference
    with prog.stage("Stage1 流动性/ST过滤"):
        candidates = []
        st_count = 0
        price_count = 0
        amount_count = 0

        for q in quotes_list:
            code = q.get("code", "")
            name = q.get("name", "")
            price = q.get("price")
            amount = q.get("amount") or 0.0

            if not code or not name or price is None:
                continue

            if "ST" in name or "*" in name or "退" in name:
                st_count += 1
                continue

            if price < 2.0:
                price_count += 1
                continue

            if amount < args.min_volume_amount:
                amount_count += 1
                continue

            code6 = "".join(ch for ch in code if ch.isdigit())[-6:]
            if code6.startswith(("43", "44", "83", "87", "82")):
                continue

            candidates.append(q)

        prog.step(
            f"剔除 ST={st_count} 低价={price_count} 低成交额={amount_count} "
            f"→ 候选池 {len(candidates)} 只"
        )
        candidates.sort(key=lambda x: x.get("amount", 0.0), reverse=True)
        selected_pool = candidates[: args.top_n]
        prog.step(f"按成交额取 Top-{args.top_n} → {len(selected_pool)} 只待拉 K 线")

    with prog.stage("Stage1 批量K线", lambda: f"{len(kline_by_code)}/{len(selected_pool)} 成功"):
        chunk_size = 30
        batches = [
            selected_pool[i : i + chunk_size]
            for i in range(0, len(selected_pool), chunk_size)
        ]
        prog.step(f"分 {len(batches)} 批并发拉取 120 日 K 线")

        def fetch_batch_kline(chunk):
            codes_str = ",".join(c["code"][-6:] for c in chunk)
            ok_batch, _raw_batch, res_batch = run_a_share_script(
                "fetch_history.py",
                ["--kline-batch", codes_str, "--count", "120", "--json"],
                timeout=50,
            )
            if ok_batch and isinstance(res_batch, dict):
                return res_batch.get("results", [])
            return []

        batch_results: list = []
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(fetch_batch_kline, chunk): chunk for chunk in batches}
            for fut in as_completed(futures):
                batch_results.extend(fut.result())

        kline_by_code: Dict[str, list] = {}
        for r in batch_results:
            if not r.get("ok"):
                continue
            code = r.get("code", "")
            data = r.get("data", [])
            if data:
                kline_by_code[code[-6:]] = data

    # If the selected strategy is sentiment-based, we pre-fetch sentiment data in batch for selected_pool
    sentiment_by_code: Dict[str, Dict[str, Any]] = {}
    if args.strategy in ["em_hot_momentum", "em_fomo_exit"]:
        with prog.stage("Stage1.2 批量东财情绪热度", lambda: f"{len(sentiment_by_code)}/{len(selected_pool)} 成功"):
            prog.step(f"并发获取 {len(selected_pool)} 只股票的东财人气和粉丝趋势数据")
            
            def fetch_one_sentiment(item):
                code6 = item["code"][-6:]
                ok, _raw, data = run_a_share_script(
                    "fetch_stock_events.py",
                    ["--code", code6, "--limit", "15", "--json"],
                    timeout=65,
                )
                if ok and isinstance(data, dict):
                    return code6, data.get("sentiment") or {}
                return code6, {}

            # Using a larger workers pool since these are purely network-bound I/O tasks
            with ThreadPoolExecutor(max_workers=10) as ex:
                futures = {ex.submit(fetch_one_sentiment, item): item for item in selected_pool}
                for fut in as_completed(futures):
                    code6, sent = fut.result()
                    if sent:
                        sentiment_by_code[code6] = sent

    with prog.stage(
        f"Stage1 技术初筛({args.strategy})",
        lambda: f"命中 {len(shortlist)} 只",
    ):
        shortlist = []
        for q in selected_pool:
            code6 = q["code"][-6:]
            if code6 not in kline_by_code:
                continue

            hist_data = kline_by_code[code6]
            df = pd.DataFrame(hist_data)
            if len(df) < 60:
                continue

            try:
                df = calculate_indicators(df)
            except Exception as e:
                logger.warning(f"Failed indicator calculation for {code6}: {e}")
                continue

            screen_result = None
            if args.strategy == "trend_pullback":
                screen_result = screen_trend_pullback(df)
            elif args.strategy == "macd_resonance":
                screen_result = screen_macd_resonance(df)
            elif args.strategy == "macd_second_golden_cross":
                screen_result = screen_macd_second_golden_cross(df)
            elif args.strategy == "em_hot_momentum":
                screen_result = screen_em_hot_momentum(df, sentiment_by_code.get(code6, {}))
            elif args.strategy == "em_fomo_exit":
                screen_result = screen_em_fomo_exit(df, sentiment_by_code.get(code6, {}))

            if screen_result:
                screen_result["code"] = q["code"]
                screen_result["name"] = q["name"]
                screen_result["price"] = q["price"]
                shortlist.append(screen_result)

        shortlist.sort(key=lambda x: x["score"], reverse=True)
        if shortlist:
            top = shortlist[0]
            prog.step(
                f"Top1 {top['name']}({top['code'][-6:]}) score={top['score']:.2f}"
            )

    # =====================================================================
    # STAGE 1.5: Fundamental & Regulatory Filters (Dynamic Pruning)
    # =====================================================================
    with prog.stage(
        "Stage1.5 红线过滤",
        lambda: f"保留 {len(valid_shortlist)} 只, 剔除 {len(pruned_list)} 只",
    ):
        valid_shortlist = []
        pruned_list = []

        for item in shortlist[: args.validate_top * 3]:
            code = item["code"]
            name = item["name"]

            is_f_flagged, f_reason = evaluate_fundamental_flags(code, allow_loss=args.allow_loss)
            if is_f_flagged:
                prog.step(f"剔除 {name}({code[-6:]}) 基本面: {f_reason}")
                item["prune_reason"] = f_reason
                pruned_list.append(item)
                continue

            is_r_flagged, r_reason = evaluate_regulatory_flags(code, name)
            if is_r_flagged:
                prog.step(f"剔除 {name}({code[-6:]}) 监管: {r_reason}")
                item["prune_reason"] = r_reason
                pruned_list.append(item)
                continue

            valid_shortlist.append(item)
            if len(valid_shortlist) >= args.validate_top:
                break

        if not valid_shortlist and shortlist:
            logger.warning(
                "All top technical candidates were pruned! "
                "Falling back to unpruned technical list with warnings."
            )
            valid_shortlist = shortlist[: args.validate_top]

    # =====================================================================
    # STAGE 2: Deep Multi-Agent validation
    # =====================================================================
    parallel_config = config.copy()
    parallel_config["output_language"] = "Chinese"
    parallel_config["checkpoint_enabled"] = False
    parallel_config["recommend_force"] = args.force
    # 单线程深度研判时沿用 analyze 的节点级进度；多线程仅打每只耗时
    use_graph_progress = args.concurrency <= 1 and len(valid_shortlist) == 1
    parallel_config["progress_logging"] = use_graph_progress
    if not use_graph_progress:
        os.environ.setdefault("TRADINGAGENTS_PROGRESS_LOG", "0")

    validated_results: List[Dict[str, Any]] = []
    with prog.stage(
        "Stage2 多智能体深度研判",
        lambda: f"{len(validated_results)} 只完成",
    ):
        if valid_shortlist:
            workers = min(args.concurrency, len(valid_shortlist))
            if workers <= 1:
                prog.step("并发度为 1，使用单进程顺序执行...")
                for item in valid_shortlist:
                    res = run_multi_agent_graph(item, parallel_config, trade_date)
                    validated_results.append(res)
            else:
                prog.step(f"并发度={workers}, 待分析={len(valid_shortlist)} 只 (物理进程内存隔离模式)")
                try:
                    with ProcessPoolExecutor(max_workers=workers) as executor:
                        futures = {
                            executor.submit(run_multi_agent_graph, item, parallel_config, trade_date): item
                            for item in valid_shortlist
                        }
                        for fut in as_completed(futures):
                            validated_results.append(fut.result())
                except Exception as e:
                    logger.warning(f"ProcessPoolExecutor 启动失败: {e}，降级为单进程顺序执行...")
                    validated_results = []
                    for item in valid_shortlist:
                        res = run_multi_agent_graph(item, parallel_config, trade_date)
                        validated_results.append(res)
        else:
            prog.step("无候选股，跳过深度研判")

    # =====================================================================
    # STAGE 3: Portfolio Ranking & Final Report Generation
    # =====================================================================
    with prog.stage(
        "Stage3 报告生成",
        lambda: f"推荐 {len(recommended_stocks)} 只",
    ):
        rating_priority = {"Buy": 1, "Overweight": 2, "Hold": 3, "Sell": 4, "FAILED": 5}
        validated_results.sort(
            key=lambda x: (
                rating_priority.get(x.get("rating", "FAILED"), 5),
                -x["score"],
            )
        )

        recommended_stocks = [
            r
            for r in validated_results
            if r.get("rating") in ["Buy", "Overweight", "Hold"]
        ]

        rec_dir = Path(config["results_dir"]) / "recommendations" / trade_date
        rec_dir.mkdir(parents=True, exist_ok=True)

        json_path = rec_dir / "recommended_stocks.json"
        report_path = rec_dir / "recommended_report.md"

        summary = {
            "trade_date": trade_date,
            "strategy": args.strategy,
            "parameters": {
                "top_n": args.top_n,
                "validate_top": args.validate_top,
                "min_volume_amount": args.min_volume_amount,
            },
            "all_screened_count": len(shortlist),
            "pruned": [
                {
                    "code": p["code"],
                    "name": p["name"],
                    "score": p["score"],
                    "prune_reason": p["prune_reason"],
                }
                for p in pruned_list
            ],
            "recommendations": [
                {
                    "code": r["code"],
                    "name": r["name"],
                    "score": r["score"],
                    "price": r["price"],
                    "rating": r["rating"],
                    "metrics": r["metrics"],
                    "reason": r["reason"],
                    "report_paths": r.get("report_paths", {}),
                    "report_storage": r.get("report_storage", r.get("report_paths", {})),
                    "deep_analysis_source": r.get("deep_analysis_source"),
                    "skipped_deep_analysis": r.get("skipped_deep_analysis", False),
                }
                for r in recommended_stocks
            ],
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        prog.step(f"JSON → {json_path}")

        # Sync recommendations to local SQLite database
        try:
            from tradingagents.graph.storage import save_recommendation_to_sqlite
            for r in recommended_stocks:
                save_recommendation_to_sqlite(r, args.strategy, trade_date)
            prog.step("已将推荐结果同步至本地 SQLite 数据库中")
        except Exception as e:
            logger.warning(f"Failed to sync recommendations to SQLite: {e}")

        md_lines = [
            "#  TradingAgents 每日 A 股量化精选推荐报告",
            "",
            f"- **分析日期**: `{trade_date}`",
            f"- **筛选量化策略**: `{args.strategy}` (共初筛 `{len(shortlist)}` 只股票，通过红线过滤 `{len(valid_shortlist)}` 只)",
            f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "##  股票池精选结果摘要 (Shortlist Summary)",
            "",
            "| 股票代码 | 股票名称 | 量化分值 | 最新现价 | 智能体决策级 | 核心推荐驱动力 |",
            "|---|---|---|---|---|---|",
        ]

        for r in recommended_stocks:
            code6 = r["code"][-6:]
            md_lines.append(
                f"| `{code6}` | **{r['name']}** | {r['score']:.1f} | {r['price']:.2f} 元 | "
                f"**{r['rating']}** | {r['reason'][:40]}... |"
            )
        if not recommended_stocks:
            md_lines.append("| (今日无推荐股票) | - | - | - | - | - |")

        md_lines.extend([
            "",
            "##  多智能体深度研判详情 (Deep Agent Valuations)",
            "",
        ])

        for r in recommended_stocks:
            code6 = r["code"][-6:]
            md_lines.extend([
                f"### {r['name']} ({code6}) — 智能体评级: **{r['rating']}**",
                "",
                f"- **初筛现价**: `{r['price']:.2f} 元` | **量化技术形态得分**: `{r['score']:.1f}`",
                f"- **技术筛理由**: {r['reason']}",
                "",
            ])

            final_state_data = r.get("final_state", {})
            decision_text = final_state_data.get("final_trade_decision") or ""

            if decision_text:
                clean_decision = re.sub(r"^#+.*", "", decision_text, flags=re.MULTILINE).strip()
                md_lines.extend([
                    "####  组合经理与风控最终决策",
                    "",
                    clean_decision,
                    "",
                ])
            else:
                md_lines.append("*（多智能体报告未成功生成或该股票未给出有效决策内容）*")
                md_lines.append("")

        if pruned_list:
            md_lines.extend([
                "---",
                "## ⚠️ 动态防爆雷红线拦截详情 (Risk-Mitigated Pruning History)",
                "",
                "以下股票虽具有完美的技术买入形态，但触发了基本面亏损或重大合规、监管和暴雷风险红线，被系统一票否决：",
                "",
                "| 股票代码 | 股票名称 | 技术得分 | 红线拦截理由 |",
                "|---|---|---|---|",
            ])
            for p in pruned_list:
                md_lines.append(
                    f"| `{p['code'][-6:]}` | {p['name']} | {p['score']:.1f} | **{p.get('prune_reason')}** |"
                )
            md_lines.append("")

        report_path.write_text("\n".join(md_lines), encoding="utf-8")
        prog.step(f"Markdown → {report_path}")

    prog.finish_pipeline()

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"\nRecommended report: {report_path.resolve()}")
        print("Recommended stocks:")
        for r in recommended_stocks:
            print(f"  - {r['name']} ({r['code'][-6:]}): Rating={r['rating']}, Score={r['score']:.1f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
