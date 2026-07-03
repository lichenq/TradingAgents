"""Tuige position_grade derivation, PM mandate, and final decision enrichment."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from tradingagents.tuige.regime import position_cap_for_regime

POSITION_GRADES = ("standard", "light", "defensive", "no_trade")
_GRADE_RANK = {g: i for i, g in enumerate(POSITION_GRADES)}


def _min_grade(a: str, b: str) -> str:
    if a not in _GRADE_RANK:
        return b
    if b not in _GRADE_RANK:
        return a
    return a if _GRADE_RANK[a] <= _GRADE_RANK[b] else b


def derive_position_grade(
    tuige_ctx: Optional[Dict[str, Any]],
    setup: str,
) -> str:
    """Map regime + setup to position_grade (deterministic)."""
    if not tuige_ctx or not tuige_ctx.get("enabled"):
        return "standard"

    regime = tuige_ctx.get("effective_regime") or "rotation"
    rebalance = tuige_ctx.get("rebalance_window") or "no"
    cap = position_cap_for_regime(regime, rebalance)

    if regime == "no_trade" or cap == "no_trade":
        return "no_trade"
    if rebalance in ("yes", "watch") and setup == "relay-setups":
        return "no_trade"
    if setup == "relay-setups":
        return "light"
    if setup == "washout-breakout-setups":
        return _min_grade(cap, "light")
    if setup == "limit-up-pullback-setups":
        return _min_grade(cap, "standard")
    if setup == "trend-setups":
        return cap
    if setup == "unclassified":
        return _min_grade(cap, "light")
    return _min_grade(cap, "light")


_GRADE_SIZING: Dict[str, str] = {
    "standard": "计划总仓位的 30–50% 作为首笔；结构确认后可加至 50%",
    "light": "计划总仓位的 10–20% 试探；禁止一次性重仓",
    "defensive": "≤10% 观察仓或仅记录；无极强 trigger 不开仓",
    "no_trade": "不开新仓；仅讨论持仓风控或观望",
}


def format_position_grade_mandate(grade: str, setup: str = "") -> str:
    """PM prompt block: pre-computed Tuige position cap."""
    sizing = _GRADE_SIZING.get(grade, _GRADE_SIZING["light"])
    setup_line = f"- 个股场景: {setup}\n" if setup else ""
    return f"""
=========================================
【Tuige 仓位纪律 — 必须遵守】
{setup_line}- 仓位等级: **{grade}**
-  sizing 参考: {sizing}
- Portfolio Manager 的 Executive Summary 必须体现该仓位上限；若 rating 为 Buy/Overweight，单笔不得超过上述比例。
- position_grade=no_trade 时，rating 不得为 Buy/Overweight（除非 position_context=held 讨论减仓）。
=========================================
"""


def format_tuige_summary(ctx: Optional[Dict[str, Any]]) -> str:
    """One-line summary for Agent / bulletin headers."""
    if not ctx or not ctx.get("enabled"):
        return ""
    parts = [
        f"环境={ctx.get('effective_regime', 'rotation')}",
        f"换仓={ctx.get('rebalance_window', 'no')}",
        f"仓位上限={ctx.get('position_cap', 'light')}",
    ]
    hits = ctx.get("signal_hits") or []
    if hits:
        parts.append(f"信号={','.join(hits[:3])}")
    return " | ".join(parts)


def _extract_existing_grade(text: str) -> Optional[str]:
    m = re.search(r"\*\*Position Grade\*\*:\s*(\w+)", text, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    m = re.search(r"\*\*仓位等级\*\*:\s*(\S+)", text)
    if m:
        return m.group(1).lower()
    return None


def enrich_final_trade_decision(
    decision_md: str,
    *,
    position_grade: str,
    tuige_setup: str = "",
    tuige_summary: str = "",
) -> str:
    """Ensure final_trade_decision.md contains Tuige position_grade block."""
    body = (decision_md or "").strip()
    if not body or not position_grade:
        return body

    existing = _extract_existing_grade(body)
    if existing == position_grade and "**Tuige Setup**" in body:
        return body

    lines = [body, ""]
    if tuige_setup:
        lines.append(f"**Tuige Setup**: {tuige_setup}")
    lines.append(f"**Position Grade**: {position_grade}")
    sizing = _GRADE_SIZING.get(position_grade, "")
    if sizing:
        lines.append(f"**Position Sizing (Tuige)**: {sizing}")
    if tuige_summary:
        lines.append(f"**Tuige Context**: {tuige_summary}")
    return "\n".join(lines)
