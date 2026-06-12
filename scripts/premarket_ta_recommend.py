#!/usr/bin/env python3
"""Run Stage-1 recommend per TOP-N sector from premarket sectors.json."""
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

from tradingagents.dataflows.sector_mapping import (  # noqa: E402
    get_danginvest_boards,
    get_eastmoney_concepts,
    get_eastmoney_industries,
    resolve,
)

TA = Path.home() / ".cursor/skills/trading-agents/run.sh"
DEFAULT_BOARDS = int(os.environ.get("PREMARKET_TA_BOARDS", "3"))


def board_candidates(industry: str) -> tuple[str, list[str]]:
    """Map fund-flow industry → ordered board names for recommend --board."""
    canonical = resolve(industry)
    seen: set[str] = set()
    candidates: list[str] = []

    def add(name: str) -> None:
        n = (name or "").strip()
        if n and n not in seen:
            seen.add(n)
            candidates.append(n)

    for n in get_eastmoney_industries(canonical):
        add(n)
    for n in get_eastmoney_concepts(canonical):
        add(n)
    for n in get_danginvest_boards(canonical):
        add(n)
    add(canonical)
    return canonical, candidates


def _boards_from_summary(data: dict, limit: int) -> list[str]:
    sectors = data.get("top_sectors_by_fund_flow") or []
    return [s.get("industry", "") for s in sectors[:limit] if s.get("industry")]


def _run_board_once(
    board: str,
    *,
    strategy: str,
    top_n: int,
    validate_top: int,
    concurrency: int,
) -> dict:
    env = os.environ.copy()
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(k, None)
    env["NO_PROXY"] = "*"
    cmd = [
        str(TA),
        "recommend",
        "--strategy", strategy,
        "--board", board,
        "--top-n", str(top_n),
        "--validate-top", str(validate_top),
        "--skip-curation",
        "--concurrency", str(concurrency),
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        return {"ok": False, "board": board, "error": (proc.stderr or proc.stdout)[-300:]}
    try:
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        payload = json.loads(lines[-1])
    except (json.JSONDecodeError, IndexError):
        return {"ok": False, "board": board, "error": "no json in recommend output"}
    recs = payload.get("recommendations") or payload.get("validated") or []
    return {"ok": True, "board": board, "count": len(recs), "recommendations": recs[:10]}


def _run_board(
    industry: str,
    *,
    strategy: str,
    top_n: int,
    validate_top: int,
    concurrency: int,
) -> dict:
    canonical, candidates = board_candidates(industry)
    last: dict = {"ok": False, "board": industry, "error": "no candidates"}
    for board in candidates:
        last = _run_board_once(
            board,
            strategy=strategy,
            top_n=top_n,
            validate_top=validate_top,
            concurrency=concurrency,
        )
        if last.get("ok"):
            last["industry"] = industry
            last["canonical"] = canonical
            last["board_resolved"] = board
            last["tried_boards"] = candidates
            return last
    last["industry"] = industry
    last["canonical"] = canonical
    last["tried_boards"] = candidates
    return last


def run_ta_screen(sectors_path: Path, *, boards_limit: int = DEFAULT_BOARDS) -> dict:
    data = json.loads(sectors_path.read_text(encoding="utf-8"))
    boards = _boards_from_summary(data, boards_limit)
    strategy = os.environ.get("PREMARKET_TA_STRATEGY", "trend_pullback")
    top_n = int(os.environ.get("PREMARKET_TA_TOP_N", "40"))
    validate_top = int(os.environ.get("PREMARKET_TA_VALIDATE_TOP", "0"))
    concurrency = int(os.environ.get("PREMARKET_TA_CONCURRENCY", "2"))

    results = [
        _run_board(b, strategy=strategy, top_n=top_n, validate_top=validate_top, concurrency=concurrency)
        for b in boards
    ]
    merged: list[dict] = []
    seen: set[str] = set()
    for block in results:
        label = block.get("industry") or block.get("board")
        for rec in block.get("recommendations") or []:
            code = str(rec.get("code") or "")[-6:]
            if not code or code in seen:
                continue
            seen.add(code)
            merged.append({**rec, "board": label, "board_resolved": block.get("board_resolved")})
    return {
        "ok": any(r.get("ok") for r in results),
        "boards": boards,
        "by_board": results,
        "merged": merged[:15],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sectors_json", help="Path to *_sectors.json")
    parser.add_argument("--boards", type=int, default=DEFAULT_BOARDS)
    parser.add_argument("--write-back", action="store_true", help="Merge ta_screen into sectors json")
    args = parser.parse_args()

    path = Path(args.sectors_json)
    out = run_ta_screen(path, boards_limit=args.boards)
    if args.write_back and path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        data["ta_screen"] = out
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
