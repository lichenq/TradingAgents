#!/usr/bin/env python3
"""Load sector_rotation_forecast and attach to premarket sector summary."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tradingagents.dataflows.rotation_forecast import (
    lookup_forecast_entry,
    load_forecast_raw,
    sector_entries,
)

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


def attach_forecast(sectors: list[dict[str, Any]], forecast: dict[str, Any]) -> dict[str, Any]:
    highlights: list[dict[str, Any]] = []
    sectors_fc = sector_entries(forecast)
    for s in sectors:
        ind = s.get("industry") or ""
        entry = lookup_forecast_entry(ind, sectors_fc)
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

    source = "sector_rotation_forecast.json" if sectors_fc else ""
    return {
        "ok": bool(highlights),
        "highlights": highlights[:5],
        "source": source,
    }
