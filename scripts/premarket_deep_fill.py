#!/usr/bin/env python3
"""Deep-fill missing reports for premarket candidates; optional Stage-3 curation."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.dataflows.config import get_config  # noqa: E402
from tradingagents.dataflows.trade_date import resolve_default_trade_date  # noqa: E402
from tradingagents.graph.storage import query_deep_report, query_report_flexible  # noqa: E402
from tradingagents.recommend.portfolio_curator import curate_final_recommendations  # noqa: E402
from tradingagents.agents.utils.rating import parse_rating  # noqa: E402

TA = Path.home() / ".cursor/skills/trading-agents/run.sh"
MAX_NEW = int(os.environ.get("PREMARKET_DEEP_MAX_NEW", "2"))
MAX_SECTORS = int(os.environ.get("PREMARKET_DEEP_SECTORS", "3"))
MAX_PER_SECTOR = int(os.environ.get("PREMARKET_DEEP_PER_SECTOR", "2"))


def _code6(val: object) -> str:
    digits = "".join(ch for ch in str(val or "") if ch.isdigit())
    return digits[-6:].zfill(6) if len(digits) >= 6 else ""


def collect_candidates(summary: dict) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for sector in (summary.get("top_sectors_by_fund_flow") or [])[:MAX_SECTORS]:
        ind = sector.get("industry") or ""
        for source in ("ta_pullback", "board_picks", "limit_up_leaders"):
            for row in (sector.get(source) or [])[:MAX_PER_SECTOR]:
                code = _code6(row.get("code"))
                if not code or code in seen:
                    continue
                seen.add(code)
                out.append({
                    "code": code,
                    "name": row.get("name") or code,
                    "sector": ind,
                    "source": source,
                    "score": row.get("score"),
                    "reason": row.get("signal") or source,
                })
    return out


def _item_from_sqlite(code: str, name: str, row: dict) -> dict:
    text = row.get("final_trade_decision") or row.get("trader_investment_plan") or ""
    return {
        "code": code,
        "name": name,
        "rating": parse_rating(str(text)),
        "final_state": {"complete_report": row.get("complete_report") or ""},
        "deep_analysis_source": "sqlite",
        "skipped_deep_analysis": True,
    }


def _run_analyze(code: str) -> bool:
    env = os.environ.copy()
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(k, None)
    env["NO_PROXY"] = "*"
    env.setdefault("TRADINGAGENTS_MARKET", "cn")
    env.setdefault("TRADINGAGENTS_OUTPUT_LANGUAGE", "Chinese")
    proc = subprocess.run(
        [str(TA), "analyze", "--ticker", code, "--json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=int(os.environ.get("PREMARKET_DEEP_ANALYZE_TIMEOUT", "900")),
    )
    return proc.returncode == 0


def deep_fill(summary: dict, *, curate: bool) -> dict:
    config = get_config()
    results_dir = config.get("results_dir") or str(ROOT / "results")
    trade_date = resolve_default_trade_date()
    candidates = collect_candidates(summary)

    validated: list[dict] = []
    analyzed_new: list[str] = []
    reused: list[str] = []

    for cand in candidates:
        code = cand["code"]
        row = query_deep_report(results_dir, code, trade_date)
        if row:
            reused.append(code)
            validated.append(_item_from_sqlite(code, cand["name"], row))
            continue
        if len(analyzed_new) >= MAX_NEW:
            continue
        if _run_analyze(code):
            analyzed_new.append(code)
            row = query_report_flexible(results_dir, code, trade_date)
            if row:
                validated.append(_item_from_sqlite(code, cand["name"], row))

    curation_meta: dict = {"skipped": True}
    picks: list[dict] = []
    if curate and validated:
        picks, curation_meta = curate_final_recommendations(
            validated, config, trade_date, skip=False,
        )

    return {
        "ok": True,
        "trade_date": trade_date,
        "candidates": len(candidates),
        "reused_sqlite": reused,
        "analyzed_new": analyzed_new,
        "validated_count": len(validated),
        "recommended": picks,
        "portfolio_summary": curation_meta.get("portfolio_summary") or "",
        "curation": curation_meta,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sectors_json")
    parser.add_argument("--write-back", action="store_true")
    parser.add_argument(
        "--curate",
        action="store_true",
        default=os.environ.get("PREMARKET_DEEP_CURATE", "0").strip().lower() in ("1", "true", "yes"),
    )
    args = parser.parse_args()

    path = Path(args.sectors_json)
    summary = json.loads(path.read_text(encoding="utf-8"))
    out = deep_fill(summary, curate=args.curate)
    if args.write_back:
        summary["deep_curation"] = out
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
