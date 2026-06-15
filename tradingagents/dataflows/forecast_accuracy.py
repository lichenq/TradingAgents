"""Forecast category vs next-session fund-flow accuracy tracking."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from tradingagents.dataflows.rotation_forecast import (
    DANGER_CATEGORIES,
    lookup_forecast_entry,
    sector_entries,
)

BULLISH_CATEGORIES = frozenset({"ADV_ACCUMULATION", "MOM_INFLOW", "REVERSAL_BOUNCE"})


def _results_dir(results_dir: Path | None = None) -> Path:
    if results_dir is not None:
        return Path(results_dir)
    from tradingagents.default_config import DEFAULT_CONFIG

    return Path(DEFAULT_CONFIG["results_dir"])


def _category_hit(category: str, inflow_yi: float) -> bool:
    if category in DANGER_CATEGORIES:
        return inflow_yi < 0
    if category in BULLISH_CATEGORIES:
        return inflow_yi > 0
    return True


def record_forecast_accuracy(
    forecast: Dict[str, Any],
    sectors_flow: List[Dict[str, Any]],
    *,
    results_dir: Path | None = None,
    session_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Score prior forecast categories against observed sector fund flows."""
    results_dir = _results_dir(results_dir)
    session_date = session_date or date.today().strftime("%Y-%m-%d")
    fc_sectors = sector_entries(forecast)
    if not fc_sectors:
        return {"recorded": False, "reason": "empty_forecast"}

    rows: List[Dict[str, Any]] = []
    by_category: Dict[str, List[bool]] = {}

    for sec in sectors_flow:
        industry = str(sec.get("industry") or "").strip()
        if not industry:
            continue
        inflow = float(sec.get("main_net_inflow_yi") or 0)
        entry = lookup_forecast_entry(industry, fc_sectors)
        if not entry:
            continue
        category = str(entry.get("category") or "NORMAL")
        hit = _category_hit(category, inflow)
        rows.append({
            "industry": industry,
            "category": category,
            "inflow_yi": inflow,
            "hit": hit,
        })
        by_category.setdefault(category, []).append(hit)

    cat_stats: Dict[str, Dict[str, Any]] = {}
    for cat, hits in by_category.items():
        cat_stats[cat] = {
            "count": len(hits),
            "hit_rate": sum(hits) / len(hits),
        }

    record = {
        "session_date": session_date,
        "forecast_trade_date": (forecast.get("_meta") or {}).get("trade_date"),
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_count": len(rows),
        "by_category": cat_stats,
        "details": rows[:20],
    }

    out_dir = results_dir / "forecast_accuracy"
    out_dir.mkdir(parents=True, exist_ok=True)
    history_path = out_dir / "history.jsonl"
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    aggregated = aggregate_category_accuracy(results_dir)
    latest_path = out_dir / "latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(aggregated, f, ensure_ascii=False, indent=2)

    return {"recorded": True, "record": record, "aggregated": aggregated}


def aggregate_category_accuracy(
    results_dir: Path | None = None,
    *,
    max_records: int = 30,
) -> Dict[str, Any]:
    results_dir = _results_dir(results_dir)
    history_path = results_dir / "forecast_accuracy" / "history.jsonl"
    if not history_path.is_file():
        return {"by_category": {}, "records": 0}

    records: List[Dict[str, Any]] = []
    with open(history_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    records = records[-max_records:]
    by_category: Dict[str, List[bool]] = {}
    for rec in records:
        for cat, stats in (rec.get("by_category") or {}).items():
            count = int(stats.get("count") or 0)
            hit_rate = stats.get("hit_rate")
            if count <= 0 or hit_rate is None:
                continue
            hits = int(round(float(hit_rate) * count))
            by_category.setdefault(cat, []).extend([True] * hits + [False] * (count - hits))

    out_stats: Dict[str, Dict[str, Any]] = {}
    for cat, hits in by_category.items():
        out_stats[cat] = {
            "count": len(hits),
            "hit_rate": sum(hits) / len(hits),
        }

    demoted = [
        cat for cat, st in out_stats.items()
        if st["count"] >= 3 and st["hit_rate"] < 0.5
    ]

    return {
        "records": len(records),
        "by_category": out_stats,
        "demoted_categories": demoted,
    }


def category_demoted(
    category: str,
    results_dir: Path | None = None,
) -> bool:
    agg = aggregate_category_accuracy(results_dir)
    return category in agg.get("demoted_categories", [])
