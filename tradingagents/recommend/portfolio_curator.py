"""Stage-3 portfolio curation: read full deep reports before final recommendations."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from tradingagents.agents.schemas import PortfolioRating
from tradingagents.agents.utils.agent_utils import get_language_instruction
from tradingagents.agents.utils.rating import RATINGS_5_TIER, parse_rating
from tradingagents.agents.utils.structured import bind_structured
from tradingagents.dataflows.report_paths import report_bundle_dir
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.storage import query_report_flexible
from tradingagents.llm_clients import create_llm_client

logger = logging.getLogger(__name__)

MIN_REPORT_CHARS = 200
REPORT_CHARS_PER_STOCK = 14_000
TOTAL_REPORT_CHAR_BUDGET = 55_000
_INCLUDE_RATINGS = frozenset({"Buy", "Overweight", "Hold"})


class CuratedStockPick(BaseModel):
    """Per-ticker outcome after reading the full deep-analysis report."""

    code: str = Field(
        description="Candidate stock code exactly as given in the prompt (e.g. sz688008 or 688008)."
    )
    include_in_final: bool = Field(
        description=(
            "True only when the complete report was read and the stock merits inclusion "
            "in today's recommended list for a flat portfolio. False when thesis is weak, "
            "risks dominate, rating should be Underweight/Sell, or report is inconclusive."
        ),
    )
    reviewed_rating: PortfolioRating = Field(
        description="Your rating after reading the full report (may differ from Stage-2 headline)."
    )
    report_evidence: str = Field(
        description=(
            "2-4 sentences citing specific evidence from the report "
            "(analyst findings, PM decision, risk debate, verified facts)."
        ),
    )


class PortfolioCurationResult(BaseModel):
    picks: List[CuratedStockPick] = Field(
        description="One entry per candidate; must cover every ticker listed in the prompt."
    )
    portfolio_summary: str = Field(
        description="1-3 sentences on how the selected names fit together for today's book."
    )


def _normalize_code(code: str) -> str:
    digits = re.sub(r"\D", "", code or "")
    return digits[-6:] if len(digits) >= 6 else digits


def _truncate_report(text: str, limit: int) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit] + "\n\n[... report truncated for context limit ...]"


def _stitch_report_sections(row: Dict[str, Any]) -> str:
    """Build readable report text from SQLite columns when complete_report is missing."""
    sections: List[str] = []
    for key, title in (
        ("market_report", "Market Analyst"),
        ("sentiment_report", "Social Sentiment"),
        ("news_report", "News Analyst"),
        ("fundamentals_report", "Fundamentals"),
        ("investment_plan", "Research Manager"),
        ("trader_investment_plan", "Trader"),
        ("final_trade_decision", "Portfolio Manager"),
    ):
        chunk = (row.get(key) or "").strip()
        if chunk:
            sections.append(f"## {title}\n\n{chunk}")
    return "\n\n".join(sections)


def resolve_complete_report_text(
    item: Dict[str, Any],
    results_dir: str,
    trade_date: str,
) -> str:
    """Load full report text for Stage-3 (in-memory → SQLite → bundle markdown)."""
    final_state = item.get("final_state") or {}
    text = (final_state.get("complete_report") or "").strip()
    if len(text) >= MIN_REPORT_CHARS:
        return text

    code = item.get("code") or ""
    row = query_report_flexible(results_dir, code, trade_date)
    if row:
        complete = (row.get("complete_report") or "").strip()
        if len(complete) >= MIN_REPORT_CHARS:
            return complete
        stitched = _stitch_report_sections(row)
        if len(stitched) >= MIN_REPORT_CHARS:
            return stitched

    bundle = report_bundle_dir(results_dir, code, trade_date)
    for name in ("complete_report.md", "final_trade_decision.md"):
        path = bundle / name
        if path.is_file():
            disk = path.read_text(encoding="utf-8").strip()
            if len(disk) >= MIN_REPORT_CHARS:
                return disk

    ftd = (final_state.get("final_trade_decision") or "").strip()
    if ftd:
        return ftd
    return ""


def _legacy_filter(validated_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rating_priority = {"Buy": 1, "Overweight": 2, "Hold": 3, "Sell": 4, "FAILED": 5}
    ordered = sorted(
        validated_results,
        key=lambda x: (
            rating_priority.get(x.get("rating", "FAILED"), 5),
            -float(x.get("score") or 0),
        ),
    )
    return [r for r in ordered if r.get("rating") in _INCLUDE_RATINGS]


def _apply_curation_picks(
    validated_results: List[Dict[str, Any]],
    picks: List[CuratedStockPick],
) -> List[Dict[str, Any]]:
    by_code6 = {_normalize_code(r.get("code", "")): r for r in validated_results}
    selected: List[Dict[str, Any]] = []
    for pick in picks:
        if not pick.include_in_final:
            continue
        if pick.reviewed_rating.value not in _INCLUDE_RATINGS:
            continue
        item = by_code6.get(_normalize_code(pick.code))
        if not item:
            continue
        item = dict(item)
        item["rating"] = pick.reviewed_rating.value
        item["curation_evidence"] = pick.report_evidence
        item["curation_reviewed"] = True
        selected.append(item)
    rating_priority = {"Buy": 1, "Overweight": 2, "Hold": 3}
    selected.sort(
        key=lambda x: (
            rating_priority.get(x.get("rating", "Hold"), 3),
            -float(x.get("score") or 0),
        ),
    )
    return selected


def _parse_curation_freetext(
    text: str,
    candidates: List[Dict[str, Any]],
) -> List[CuratedStockPick]:
    """Best-effort parse when structured output is unavailable."""
    picks: List[CuratedStockPick] = []
    for item in candidates:
        code6 = _normalize_code(item.get("code", ""))
        include = False
        reviewed = parse_rating(
            (item.get("final_state") or {}).get("final_trade_decision") or "",
            default=item.get("rating") or "Hold",
        )
        pattern = re.compile(
            rf"(?:{code6}|{item.get('name','')}).{{0,120}}?(include|exclude|纳入|剔除)",
            re.IGNORECASE | re.DOTALL,
        )
        if pattern.search(text):
            include = "include" in text.lower() or "纳入" in text
        elif reviewed in _INCLUDE_RATINGS:
            include = True
        picks.append(
            CuratedStockPick(
                code=item.get("code") or code6,
                include_in_final=include,
                reviewed_rating=PortfolioRating(reviewed),
                report_evidence="Parsed from free-text curation fallback.",
            )
        )
    return picks


def curate_final_recommendations(
    validated_results: List[Dict[str, Any]],
    config: Dict[str, Any],
    trade_date: str,
    *,
    skip: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read complete reports via LLM and return final recommended list.

    Returns (recommended_stocks, curation_meta).
    """
    meta: Dict[str, Any] = {"skipped": skip, "method": "legacy"}
    if skip or not validated_results:
        return _legacy_filter(validated_results), meta

    candidates = [r for r in validated_results if r.get("rating") != "FAILED"]
    if not candidates:
        meta["reason"] = "all_failed"
        return [], meta

    report_blocks: List[str] = []
    budget_left = TOTAL_REPORT_CHAR_BUDGET
    thin_codes: List[str] = []
    results_dir = config.get("results_dir") or DEFAULT_CONFIG["results_dir"]

    for item in candidates:
        code = item.get("code") or ""
        code6 = _normalize_code(code)
        name = item.get("name") or code6
        report_text = resolve_complete_report_text(item, results_dir, trade_date)
        if len(report_text) < MIN_REPORT_CHARS:
            thin_codes.append(code6)
            continue
        per_limit = min(REPORT_CHARS_PER_STOCK, max(4000, budget_left // max(1, len(candidates))))
        chunk = _truncate_report(report_text, per_limit)
        budget_left -= len(chunk)
        stage2_rating = item.get("rating") or "Hold"
        report_blocks.append(
            f"### {name} ({code6})\n"
            f"- Stage-1 quant score: {item.get('score')}\n"
            f"- Stage-2 headline rating: {stage2_rating}\n"
            f"- Technical reason: {item.get('reason', '')}\n\n"
            f"{chunk}\n"
        )

    if thin_codes:
        meta["thin_report_codes"] = thin_codes
        logger.warning(
            "Stage-3 curation: missing readable report for %s — excluded from LLM review",
            ", ".join(thin_codes),
        )

    if not report_blocks:
        meta["reason"] = "no_readable_reports"
        meta["method"] = "legacy_no_reports"
        return _legacy_filter(validated_results), meta

    provider = config.get("llm_provider") or DEFAULT_CONFIG["llm_provider"]
    model = config.get("deep_think_llm") or DEFAULT_CONFIG["deep_think_llm"]
    base_url = config.get("backend_url")
    llm_client = create_llm_client(provider=provider, model=model, base_url=base_url)
    llm = llm_client.get_llm()
    structured_llm = bind_structured(llm, PortfolioCurationResult, "Recommend Curator")

    codes_list = ", ".join(_normalize_code(c.get("code", "")) for c in candidates)
    prompt = f"""You are the Portfolio Curator for a daily A-share recommendation book (flat portfolio, no existing positions).

**Mandatory process**
1. Read each candidate's COMPLETE deep-analysis report below (all sections — analysts, debate, trader, portfolio manager).
2. Do NOT rely only on the Stage-2 headline rating; re-judge from report evidence.
3. Set include_in_final=true only for names you would actually recommend today after reading the full report.
4. Downgrade to Underweight/Sell in reviewed_rating when the report shows fatal risks, hallucinations, or weak thesis.
5. Every candidate code must appear exactly once in picks: {codes_list}

**Inclusion rules (flat book)**
- include_in_final=true only when reviewed_rating is Buy, Overweight, or Hold AND the report supports actionable exposure.
- Exclude (include_in_final=false) when PM/trader says wait, avoid entry, or risks dominate.
- Prefer quality over quantity; it is valid to recommend zero stocks if none pass.

**Trade date**: {trade_date}
**Allowed ratings**: {", ".join(RATINGS_5_TIER)}

---

## Candidate reports

{chr(10).join(report_blocks)}

---

Respond with structured picks for every candidate and a brief portfolio_summary.{get_language_instruction()}"""

    try:
        if structured_llm is not None:
            result = structured_llm.invoke(prompt)
            picks = result.picks
            meta["portfolio_summary"] = result.portfolio_summary
        else:
            response = llm.invoke(prompt)
            free_text = str(getattr(response, "content", response))
            picks = _parse_curation_freetext(free_text, candidates)
            meta["portfolio_summary"] = free_text[:500]
        meta["method"] = "llm"
        selected = _apply_curation_picks(validated_results, picks)
        if not selected:
            # LLM read reports and chose zero names — do not override with rating sort.
            meta["selected_count"] = 0
            meta["intentional_empty"] = True
            return [], meta
        meta["selected_count"] = len(selected)
        return selected, meta
    except Exception as exc:
        logger.error("Stage-3 LLM curation failed (%s); falling back to rating sort", exc)
        meta["error"] = str(exc)
        meta["method"] = "legacy_after_error"
        return _legacy_filter(validated_results), meta
