#!/usr/bin/env python3
"""Load sector_rotation_forecast and attach to premarket sector summary."""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from tradingagents.dataflows.sector_mapping import get_match_names

CATEGORY_LABEL = {
    "ADV_ACCUMULATION": "逆向吸筹",
    "MOM_INFLOW": "强趋势流入",
    "QUIET_ACCUMULATION": "静悄悄建仓",
    "NORMAL": "正常震荡",
    "FOMO_DISTRIBUTION": "拉高派发",
    "PANIC_EXIT": "恐慌离场",
    "SYSTEMIC_LIQUIDATION": "主力出逃",
}


def _results_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    raw = os.environ.get("TRADINGAGENTS_RESULTS_DIR", str(root / "results"))
    return Path(raw)


def load_forecast_raw(results_dir: Path | None = None) -> dict[str, Any]:
    base = results_dir or _results_dir()
    json_path = base / "recommendations" / "sector_rotation_forecast.json"
    if json_path.is_file():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass

    try:
        from tradingagents.graph.storage import query_sector_rotation

        row = query_sector_rotation(base, date.today().isoformat())
        if row:
            raw = row.get("forecast_json")
            if isinstance(raw, str) and raw.strip():
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            if isinstance(raw, dict):
                return raw
    except Exception:
        pass
    return {}


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


def attach_forecast(sectors: list[dict[str, Any]], forecast: dict[str, Any]) -> dict[str, Any]:
    highlights: list[dict[str, Any]] = []
    for s in sectors:
        ind = s.get("industry") or ""
        entry = lookup_forecast_entry(ind, forecast)
        if not entry:
            continue
        cat = entry.get("category") or "NORMAL"
        enriched = {
            "category": cat,
            "category_label": CATEGORY_LABEL.get(cat, cat),
            "probability": entry.get("probability"),
            "action_advice": entry.get("action_advice"),
            "main_flow_t0_yi": entry.get("main_flow_t0_yi"),
        }
        s["forecast"] = enriched
        highlights.append({"industry": ind, **enriched})

    source = "sector_rotation_forecast.json" if forecast else ""
    return {
        "ok": bool(highlights),
        "highlights": highlights[:5],
        "source": source,
    }
