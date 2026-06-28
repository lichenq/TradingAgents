"""Structured failure-mode tags from post-audit outcomes."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

ACTIONABLE_RATINGS = frozenset({"Buy", "Overweight"})


def _parse_metrics(rec: Dict[str, Any]) -> Dict[str, Any]:
    raw = rec.get("metrics")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def fetch_pe_ttm(code: str, trade_date: str, config: Dict[str, Any]) -> Optional[float]:
    from tradingagents.dataflows.cn_valuation import fetch_cn_valuation_payload

    code6 = "".join(ch for ch in str(code or "") if ch.isdigit())[-6:]
    ok, payload, _ = fetch_cn_valuation_payload(code6, trade_date, config)
    if not ok or not isinstance(payload, dict):
        return None
    pe = payload.get("pe_ttm")
    if pe is None:
        return None
    try:
        pe_f = float(pe)
    except (TypeError, ValueError):
        return None
    return pe_f if pe_f > 0 else None


def classify_failure_modes(
    rec: Dict[str, Any],
    raw_return: float,
    *,
    pe_ttm: Optional[float] = None,
) -> List[str]:
    """Return deterministic tags for an audited recommendation."""
    tags: List[str] = []
    rating = str(rec.get("rating") or "")
    ret = float(raw_return)
    score = float(rec.get("score") or 0)

    if ret > 0.03 and rating in ACTIONABLE_RATINGS:
        tags.append("win")
        return tags

    if rating in ("Hold", "Underweight", "Sell") and ret <= -0.03:
        tags.append("bearish_correct")
        return tags

    if rating not in ACTIONABLE_RATINGS:
        return tags

    if ret >= 0:
        return tags

    if pe_ttm is not None and pe_ttm > 60:
        tags.append("high_pe_loss")
    if ret <= -0.08:
        tags.append("large_drawdown")
    if score >= 85:
        tags.append("high_score_loss")

    reason = str(rec.get("reason") or "")
    if any(k in reason for k in ("人气", "热度", "涨停", "FOMO")):
        tags.append("sentiment_chase_loss")

    metrics = _parse_metrics(rec)
    ret3 = metrics.get("ret3") or metrics.get("近3日%")
    if ret3 is not None:
        try:
            if float(ret3) > 25:
                tags.append("overextended_loss")
        except (TypeError, ValueError):
            pass

    if not tags:
        tags.append("actionable_loss")
    return tags


def _parse_failure_modes(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
        except json.JSONDecodeError:
            return [raw]
    return []


def failure_mode_counts(
    results_dir: str | Path,
    *,
    lookback_days: int = 30,
) -> Dict[str, int]:
    from tradingagents.dataflows.audit_report import fetch_enriched_audits

    enriched = fetch_enriched_audits(results_dir, lookback_days=lookback_days)
    counter: Counter[str] = Counter()
    for row in enriched:
        ret = row.get("raw_return")
        if ret is None or float(ret) >= 0:
            continue
        for tag in _parse_failure_modes(row.get("failure_modes")):
            if tag != "win":
                counter[tag] += 1
    return dict(counter)


def format_failure_mode_summary(
    results_dir: str | Path,
    *,
    lookback_days: int = 30,
    top_n: int = 3,
) -> str:
    counts = failure_mode_counts(results_dir, lookback_days=lookback_days)
    if not counts:
        return ""
    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:top_n]
    parts = [f"{name}×{n}" for name, n in ranked]
    return "近期亏损模式: " + ", ".join(parts)
