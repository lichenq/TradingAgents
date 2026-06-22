"""Pre-debate analyst report quality checks."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

MIN_REPORT_CHARS = 200
_DATA_CITATION_RE = re.compile(
    r"\[L[1-4]\]|%\d|×\d|\d+\.\d+|PE|PB|RSI|MACD|均线|SMA|EMA|涨|跌|亿|万",
    re.IGNORECASE,
)

REPORT_SPECS: Tuple[Tuple[str, str], ...] = (
    ("market_report", "Market Analyst"),
    ("sentiment_report", "Sentiment Analyst"),
    ("news_report", "News Analyst"),
    ("fundamentals_report", "Fundamentals Analyst"),
)

_LOW_QUALITY_PREFIX = (
    "\n\n> ⚠️ **报告质量告警**：本报告过短或缺少数据引用，"
    "下游辩论须降低权重，禁止据此编造事实。\n"
)


def assess_report(report: str, *, min_chars: int = MIN_REPORT_CHARS) -> Dict[str, Any]:
    body = (report or "").strip()
    if not body:
        return {"level": "low", "reasons": ["empty"]}
    reasons: List[str] = []
    if len(body) < min_chars:
        reasons.append(f"too_short:{len(body)}<{min_chars}")
    if not _DATA_CITATION_RE.search(body):
        reasons.append("no_data_citation")
    if reasons:
        return {"level": "low", "reasons": reasons}
    return {"level": "ok", "reasons": []}


def annotate_low_quality_report(report: str) -> str:
    body = (report or "").strip()
    if not body:
        return (
            "(This report was not generated or is unavailable for this run. "
            "Do NOT assume, fabricate, or speculate on any facts, metrics, "
            "or announcements from this category.)"
        )
    if _LOW_QUALITY_PREFIX.strip() in body:
        return body
    return body + _LOW_QUALITY_PREFIX


def build_quality_gate_updates(state: dict) -> Dict[str, Any]:
    """Return state patches after assessing selected analyst reports."""
    notes: List[str] = []
    updates: Dict[str, Any] = {}

    for key, label in REPORT_SPECS:
        if not (state.get(key) or "").strip() and key not in state:
            continue
        report = state.get(key) or ""
        if not report.strip():
            notes.append(f"- {label}: 未生成报告")
            continue
        quality = assess_report(report)
        if quality["level"] != "low":
            continue
        reason = ", ".join(quality["reasons"])
        notes.append(f"- {label}: 低质量 ({reason})")
        updates[key] = annotate_low_quality_report(report)

    verified = (state.get("verified_market_facts") or "").strip()
    if verified:
        pe_match = re.search(r"TTM PE[：:]\s*([\d.]+)", verified)
        if pe_match:
            notes.append(
                f"- 行情硬数据 TTM PE={pe_match.group(1)}×：辩论中引用 PE 必须与此一致"
            )

    if notes:
        header = "## 分析师报告质检（辩论前）\n" + "\n".join(notes)
        header += (
            "\n\n辩论与决策须：① 低质量报告降权；"
            "② PE/PB/现价仅引用「行情硬数据」块；"
            "③ 不得用模型记忆填估值。"
        )
        updates["report_quality_notes"] = header
    else:
        updates["report_quality_notes"] = ""

    return updates
