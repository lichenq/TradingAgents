"""Aggregate backtest audit KPIs by strategy and rating."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from tradingagents.graph.storage import (
    query_backtest_audits,
    query_recommendations,
)


def _code6(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[-6:]


def _bucket_stats(returns: List[float]) -> Dict[str, Any]:
    if not returns:
        return {"count": 0, "win_rate": None, "avg_return": None}
    wins = sum(1 for x in returns if x > 0)
    return {
        "count": len(returns),
        "win_rate": wins / len(returns),
        "avg_return": sum(returns) / len(returns),
    }


def _lookup_recommendation(
    rec_index: Dict[tuple[str, str], Dict[str, Any]],
    ticker: str,
    recommendation_date: str,
) -> Optional[Dict[str, Any]]:
    key = (_code6(ticker), str(recommendation_date)[:10])
    if key in rec_index:
        return rec_index[key]
    return rec_index.get((ticker, str(recommendation_date)[:10]))


def fetch_enriched_audits(
    results_dir: str | Path,
    *,
    lookback_days: int = 30,
    as_of: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Load recent audits joined with recommendation strategy/rating."""
    as_of = as_of or date.today()
    since = (as_of - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    results_dir = Path(results_dir)

    audits = query_backtest_audits(results_dir, limit=500)
    audits = [
        a for a in audits
        if str(a.get("audit_date") or "")[:10] >= since
    ]
    if not audits:
        return []

    rec_index: Dict[tuple[str, str], Dict[str, Any]] = {}
    audit_dates = {
        str(a.get("recommendation_date") or "")[:10]
        for a in audits
        if a.get("recommendation_date")
    }
    for td in sorted(audit_dates):
        for rec in query_recommendations(results_dir, trade_date=td, limit=100):
            key = (_code6(rec.get("code") or ""), td)
            rec_index[key] = rec
            rec_index[(str(rec.get("code") or ""), td)] = rec

    enriched: List[Dict[str, Any]] = []
    for audit in audits:
        rec = _lookup_recommendation(
            rec_index,
            str(audit.get("ticker") or ""),
            str(audit.get("recommendation_date") or ""),
        )
        row = dict(audit)
        row["strategy"] = (rec or {}).get("strategy") or "unknown"
        row["rating"] = (rec or {}).get("rating") or "unknown"
        enriched.append(row)
    return enriched


def build_audit_report(
    results_dir: str | Path,
    *,
    lookback_days: int = 7,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """Build KPI report from recent backtest_audits joined with recommendations."""
    as_of = as_of or date.today()
    since = (as_of - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    enriched = fetch_enriched_audits(
        results_dir, lookback_days=lookback_days, as_of=as_of
    )

    all_returns = [
        float(r["raw_return"])
        for r in enriched
        if r.get("raw_return") is not None
    ]

    by_strategy: Dict[str, List[float]] = {}
    by_rating: Dict[str, List[float]] = {}
    by_horizon: Dict[str, List[float]] = {}
    by_failure_mode: Dict[str, List[float]] = {}

    for row in enriched:
        ret = row.get("raw_return")
        if ret is None:
            continue
        ret_f = float(ret)
        by_strategy.setdefault(str(row.get("strategy") or "unknown"), []).append(ret_f)
        by_rating.setdefault(str(row.get("rating") or "unknown"), []).append(ret_f)
        by_horizon.setdefault(str(row.get("days_elapsed") or "unknown"), []).append(ret_f)
        raw_modes = row.get("failure_modes")
        modes: List[str] = []
        if isinstance(raw_modes, list):
            modes = [str(m) for m in raw_modes]
        elif isinstance(raw_modes, str) and raw_modes.strip():
            try:
                parsed = json.loads(raw_modes)
                if isinstance(parsed, list):
                    modes = [str(m) for m in parsed]
            except json.JSONDecodeError:
                modes = [raw_modes]
        for mode in modes or ["untagged"]:
            by_failure_mode.setdefault(mode, []).append(ret_f)

    def _map_buckets_list(src: Dict[str, List[float]]) -> Dict[str, Dict[str, Any]]:
        return {k: _bucket_stats(v) for k, v in sorted(src.items())}

    results_path = Path(results_dir)
    rating_calibration: Dict[str, Any] = {}
    forecast_accuracy: Dict[str, Any] = {}
    try:
        from tradingagents.dataflows.rating_calibration import build_rating_calibration

        rating_calibration = build_rating_calibration(results_path, as_of=as_of)
    except Exception:
        pass
    try:
        from tradingagents.dataflows.forecast_accuracy import aggregate_category_accuracy

        forecast_accuracy = aggregate_category_accuracy(results_path)
    except Exception:
        pass

    recent_cases = []
    for row in enriched[:12]:
        recent_cases.append({
            "ticker": _code6(row.get("ticker") or ""),
            "recommendation_date": row.get("recommendation_date"),
            "audit_date": row.get("audit_date"),
            "days_elapsed": row.get("days_elapsed"),
            "strategy": row.get("strategy"),
            "rating": row.get("rating"),
            "raw_return": row.get("raw_return"),
        })

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "as_of": as_of.strftime("%Y-%m-%d"),
        "lookback_days": lookback_days,
        "since": since,
        "overall": _bucket_stats(all_returns),
        "by_strategy": _map_buckets_list(by_strategy),
        "by_rating": _map_buckets_list(by_rating),
        "by_horizon": _map_buckets_list(by_horizon),
        "by_failure_mode": _map_buckets_list(by_failure_mode),
        "recent_cases": recent_cases,
        "rating_calibration": rating_calibration,
        "forecast_accuracy": forecast_accuracy,
    }


def write_audit_report(
    results_dir: str | Path,
    *,
    lookback_days: int = 7,
    as_of: Optional[date] = None,
) -> Path:
    """Write audit KPI JSON under results/audit_reports/."""
    results_dir = Path(results_dir)
    as_of = as_of or date.today()
    report = build_audit_report(results_dir, lookback_days=lookback_days, as_of=as_of)
    out_dir = results_dir / "audit_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{as_of.strftime('%Y-%m-%d')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    latest = out_dir / "latest.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return out_path
