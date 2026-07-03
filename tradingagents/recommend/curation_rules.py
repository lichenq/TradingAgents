"""Deterministic Stage-3 hard rules before / after LLM curation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from tradingagents.agents.utils.rating import parse_rating

FINAL_ACTIONABLE_RATINGS = frozenset({"Buy", "Overweight"})
HARD_REJECT_RATINGS = frozenset({"FAILED", "Sell", "Underweight"})


@dataclass
class CurationContext:
    results_dir: str
    trade_date: str
    config: Dict[str, Any]
    cautious_sectors: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    downgrade_buy: bool = False
    strategy: str = ""
    tuige_context: Optional[Dict[str, Any]] = None
    tuige_strict: bool = False


def _force_curation_enabled() -> bool:
    return os.environ.get("TRADINGAGENTS_FORCE_CURATION", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def should_skip_curation(skip_flag: bool) -> bool:
    if _force_curation_enabled():
        return False
    env = os.environ.get("TRADINGAGENTS_RECOMMEND_SKIP_CURATION", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    return skip_flag


def build_curation_context(
    config: Dict[str, Any],
    trade_date: str,
    strategy: str,
    tuige_context: Optional[Dict[str, Any]] = None,
) -> CurationContext:
    results_dir = str(config.get("results_dir") or "results")
    cautious: Dict[str, Dict[str, Any]] = {}
    downgrade_buy = False
    tuige_strict = False
    try:
        from tradingagents.dataflows.audit_feedback_gates import build_cautious_sectors
        from tradingagents.dataflows.rating_calibration import should_downgrade_buy
        from tradingagents.tuige.context import tuige_strict as _tuige_strict

        cautious = build_cautious_sectors(results_dir)
        downgrade_buy = should_downgrade_buy(results_dir)
        tuige_strict = _tuige_strict()
    except Exception:
        pass
    return CurationContext(
        results_dir=results_dir,
        trade_date=trade_date,
        config=config,
        cautious_sectors=cautious,
        downgrade_buy=downgrade_buy,
        strategy=strategy,
        tuige_context=tuige_context,
        tuige_strict=tuige_strict,
    )


def evaluate_hard_rule(item: Dict[str, Any], ctx: CurationContext) -> Tuple[bool, str]:
    rating = str(item.get("rating") or "Hold")
    if rating in HARD_REJECT_RATINGS:
        return False, f"rating={rating}"

    if ctx.downgrade_buy and rating == "Buy":
        return False, "Buy calibration downgrade (recent Buy avg return negative)"

    if ctx.cautious_sectors:
        from tradingagents.dataflows.audit_feedback_gates import evaluate_sector_high_pe_gate

        flagged, reason = evaluate_sector_high_pe_gate(
            item.get("code") or "",
            ctx.trade_date,
            ctx.cautious_sectors,
            ctx.config,
        )
        if flagged:
            return False, reason[:200]

    ftd = (item.get("final_state") or {}).get("final_trade_decision") or ""
    parsed = parse_rating(ftd, default=rating)
    if parsed in HARD_REJECT_RATINGS:
        return False, f"report rating={parsed}"

    if rating == "Hold":
        return False, "Hold not actionable in hard rules (need Overweight/Buy)"

    if rating not in FINAL_ACTIONABLE_RATINGS:
        return False, f"rating={rating} not in final actionable set"

    if ctx.tuige_context:
        from tradingagents.tuige.stage3_gates import evaluate_tuige_setup_gate

        ok, reason = evaluate_tuige_setup_gate(
            item,
            ctx.tuige_context,
            strict=ctx.tuige_strict,
        )
        if not ok:
            return False, reason

    return True, "ok"


def apply_hard_rules(
    validated_results: List[Dict[str, Any]],
    ctx: CurationContext,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    passed: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for item in validated_results:
        ok, reason = evaluate_hard_rule(item, ctx)
        row = dict(item)
        if ok:
            row["hard_rule_pass"] = True
            passed.append(row)
        else:
            row["hard_rule_pass"] = False
            row["hard_rule_reason"] = reason
            rejected.append(row)
    return passed, rejected


def finalize_actionable_list(
    items: List[Dict[str, Any]],
    ctx: CurationContext,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in items:
        ok, reason = evaluate_hard_rule(item, ctx)
        if not ok:
            continue
        row = dict(item)
        row["curation_reviewed"] = row.get("curation_reviewed", True)
        if not row.get("curation_evidence"):
            row["curation_evidence"] = "Hard rules: actionable Buy/Overweight."
        out.append(row)
    rating_priority = {"Buy": 1, "Overweight": 2}
    out.sort(
        key=lambda x: (
            rating_priority.get(str(x.get("rating") or ""), 9),
            -float(x.get("score") or 0),
        ),
    )
    return out
