"""Rating calibration from backtest audits — detect systematic Buy optimism."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from tradingagents.dataflows.audit_report import fetch_enriched_audits


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def calibration_config() -> Dict[str, Any]:
    return {
        "lookback_days": _env_int("RATING_CALIB_LOOKBACK_DAYS", 30),
        "min_samples": _env_int("RATING_CALIB_MIN_SAMPLES", 3),
        "buy_downgrade_avg_return": _env_float("RATING_CALIB_BUY_MAX_AVG", 0.0),
    }


def _stats_for_rating(rows: List[Dict[str, Any]], rating: str) -> Dict[str, Any]:
    rets = [
        float(r["raw_return"])
        for r in rows
        if str(r.get("rating") or "") == rating and r.get("raw_return") is not None
    ]
    if not rets:
        return {"count": 0, "win_rate": None, "avg_return": None, "median_return": None}
    wins = sum(1 for x in rets if x > 0)
    sorted_rets = sorted(rets)
    mid = len(sorted_rets) // 2
    median = sorted_rets[mid]
    return {
        "count": len(rets),
        "win_rate": wins / len(rets),
        "avg_return": sum(rets) / len(rets),
        "median_return": median,
    }


def build_rating_calibration(
    results_dir: str | Path,
    *,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    cfg = calibration_config()
    enriched = fetch_enriched_audits(
        results_dir,
        lookback_days=cfg["lookback_days"],
        as_of=as_of,
    )
    by_rating: Dict[str, Dict[str, Any]] = {}
    for rating in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
        by_rating[rating] = _stats_for_rating(enriched, rating)

    buy_stats = by_rating.get("Buy") or {}
    downgrade_buy = False
    downgrade_reason = ""
    if (
        buy_stats.get("count", 0) >= cfg["min_samples"]
        and buy_stats.get("avg_return") is not None
        and float(buy_stats["avg_return"]) < cfg["buy_downgrade_avg_return"]
    ):
        downgrade_buy = True
        downgrade_reason = (
            f"Buy avg_return {float(buy_stats['avg_return']):+.1%} "
            f"< {cfg['buy_downgrade_avg_return']:+.1%} (n={buy_stats['count']})"
        )

    return {
        "lookback_days": cfg["lookback_days"],
        "by_rating": by_rating,
        "downgrade_buy": downgrade_buy,
        "downgrade_buy_reason": downgrade_reason,
    }


def should_downgrade_buy(results_dir: str | Path, *, as_of: Optional[date] = None) -> bool:
    return bool(build_rating_calibration(results_dir, as_of=as_of).get("downgrade_buy"))
