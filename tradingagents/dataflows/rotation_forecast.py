"""Sector rotation forecast load, staleness, and recommend --board auto filtering."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from tradingagents.dataflows.sector_mapping import get_match_names

META_KEY = "_meta"
DANGER_CATEGORIES = frozenset(
    {"SYSTEMIC_LIQUIDATION", "FOMO_DISTRIBUTION", "PANIC_EXIT"}
)
MIN_INFLOW_OVERRIDE_YI = 1.0


def _results_dir(results_dir: Path | None = None) -> Path:
    if results_dir is not None:
        return Path(results_dir)
    root = Path(__file__).resolve().parents[2]
    raw = os.environ.get("TRADINGAGENTS_RESULTS_DIR", str(root / "results"))
    return Path(raw)


def sector_entries(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k != META_KEY and isinstance(v, dict)}


def lookup_forecast_entry(industry: str, forecast: dict[str, Any]) -> dict[str, Any] | None:
    if not industry or not forecast:
        return None
    if industry in forecast:
        return forecast[industry]
    aliases = set(get_match_names(industry))
    for key, val in forecast.items():
        if key in aliases or key == industry:
            return val
        if key in get_match_names(industry):
            return val
    return None


def _previous_cn_trade_date(calendar_day: date | None = None) -> str:
    calendar_day = calendar_day or date.today()
    from tradingagents.dataflows.trade_date import _cn_trading_days_between, resolve_default_trade_date

    current = resolve_default_trade_date(as_of=datetime.combine(calendar_day, datetime.min.time()))
    start = calendar_day - timedelta(days=30)
    days = sorted(_cn_trading_days_between(start, calendar_day))
    prior = [d for d in days if d < current]
    return prior[-1] if prior else current


def _forecast_trade_date(data: dict[str, Any]) -> str:
    meta = data.get(META_KEY)
    if isinstance(meta, dict) and meta.get("trade_date"):
        return str(meta["trade_date"])[:10]
    dates: list[str] = []
    for entry in sector_entries(data).values():
        ut = entry.get("update_time") or ""
        if len(ut) >= 10:
            dates.append(ut[:10])
    return max(dates) if dates else ""


def is_stale_forecast(data: dict[str, Any], calendar_day: date | None = None) -> bool:
    if not data:
        return True
    forecast_td = _forecast_trade_date(data)
    if not forecast_td:
        return True
    calendar_day = calendar_day or date.today()
    from tradingagents.dataflows.trade_date import resolve_default_trade_date

    current_td = resolve_default_trade_date(
        as_of=datetime.combine(calendar_day, datetime.min.time())
    )
    prev_td = _previous_cn_trade_date(calendar_day)
    return forecast_td not in (current_td, prev_td)


def load_forecast_raw(results_dir: Path | None = None) -> dict[str, Any]:
    base = _results_dir(results_dir)
    calendar_day = date.today()

    try:
        from tradingagents.dataflows.trade_date import resolve_default_trade_date
        from tradingagents.graph.storage import parse_json_safe, query_sector_rotation

        trade_date = resolve_default_trade_date()
        row = query_sector_rotation(base, trade_date)
        if row and row.get("forecast_json"):
            raw = row["forecast_json"]
            if isinstance(raw, str) and raw.strip():
                data = parse_json_safe(raw) or {}
            elif isinstance(raw, dict):
                data = raw
            else:
                data = {}
            if isinstance(data, dict) and data and not is_stale_forecast(data, calendar_day):
                return data
    except Exception:
        pass

    json_path = base / "recommendations" / "sector_rotation_forecast.json"
    if json_path.is_file():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data and not is_stale_forecast(data, calendar_day):
                return data
        except (json.JSONDecodeError, OSError):
            pass

    return {}


def filter_hot_industries_by_forecast(
    items: list[dict[str, Any]],
    forecast: dict[str, Any],
    *,
    top_n: int = 5,
    min_inflow_override_yi: float = MIN_INFLOW_OVERRIDE_YI,
    results_dir: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Pick top industries by fund flow after forecast danger filter / T0 override."""
    sectors = sector_entries(forecast)
    kept: list[dict[str, Any]] = []
    notes: list[str] = []
    demoted_cache: dict[str, bool] = {}

    try:
        from tradingagents.dataflows.forecast_accuracy import category_demoted

        base_dir = results_dir or _results_dir()
    except Exception:
        category_demoted = None  # type: ignore[assignment,misc]
        base_dir = None

    for item in items:
        industry = str(item.get("industry") or "").strip()
        if not industry:
            continue
        inflow = float(item.get("main_net_inflow_yi") or 0)
        entry = lookup_forecast_entry(industry, sectors)
        cat = (entry or {}).get("category") or "NORMAL"
        demoted = False
        if category_demoted is not None and base_dir is not None:
            if cat not in demoted_cache:
                demoted_cache[cat] = category_demoted(cat, base_dir)
            demoted = demoted_cache[cat]
        override_threshold = min_inflow_override_yi
        if demoted and cat in DANGER_CATEGORIES:
            override_threshold = min_inflow_override_yi * 2.0
            notes.append(f"低命中率降级 {cat} → T0阈值升至 {override_threshold:.1f}亿")
        if cat in DANGER_CATEGORIES and inflow < override_threshold:
            notes.append(f"避雷跳过 {industry}（{cat}，实时流入 {inflow:.2f}亿）")
            continue
        if cat in DANGER_CATEGORIES and inflow >= override_threshold:
            notes.append(f"T0 覆盖保留 {industry}（{cat}，实时流入 {inflow:.2f}亿）")
        kept.append(item)
    selected = [str(x["industry"]) for x in kept[:top_n] if x.get("industry")]
    return selected, notes
