#!/usr/bin/env python3
"""P1 conditional alerts: auction (9:15) and theme exhaustion (10:30)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import premarket_sector_summary as sector_summary  # noqa: E402
from tradingagents.dataflows.sector_mapping import get_match_names  # noqa: E402

_run = sector_summary._run

AUCTION_GAP = float(os.environ.get("PREMARKET_AUCTION_GAP", "0.8"))
LEADER_GAP = float(os.environ.get("PREMARKET_LEADER_AUCTION_GAP", "3.0"))
PULLBACK = float(os.environ.get("PREMARKET_EXHAUSTION_PULLBACK", "5.0"))


def _load_sectors(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _open_gap_pct(quote: dict) -> float | None:
    prev = float(quote.get("昨收") or 0)
    open_px = float(quote.get("今开") or 0)
    if prev <= 0 or open_px <= 0:
        return None
    return (open_px - prev) / prev * 100


def _in_top10(industry: str, top10: set[str]) -> bool:
    if industry in top10:
        return True
    return any(alias in top10 for alias in get_match_names(industry))


def _auction_hint(gap: float | None, themes: list[str]) -> str:
    if gap is None:
        return "竞价数据不足，开盘后再确认"
    theme = "/".join(themes[:2]) if themes else "主线"
    if gap >= AUCTION_GAP:
        return f"高开→{theme}若延续可观察，不追第一脚；等9:35确认"
    if gap <= -AUCTION_GAP:
        return f"低开→{theme}降预期，只观察不追"
    return ""


def check_auction(sectors_path: str | None) -> dict:
    quote = _run("fetch_realtime.py", "--quote", "sh000001", "--json")
    gap = _open_gap_pct(quote)
    sectors = _load_sectors(sectors_path)
    themes = [s.get("industry", "") for s in sectors.get("top_sectors_by_fund_flow", [])[:3]]
    cons = sectors.get("consecutive_limit_leaders", [])[:3]

    reasons: list[str] = []
    if gap is not None and abs(gap) >= AUCTION_GAP:
        reasons.append(f"上证开盘{'高' if gap > 0 else '低'}开{gap:+.2f}%")

    hot_leaders: list[str] = []
    codes = ",".join(str(c["code"]) for c in cons if c.get("code"))
    if codes:
        rows = _run("fetch_realtime.py", "--multi-quote", codes, "--json")
        if not isinstance(rows, list):
            rows = []
        by_code = {str(r.get("代码", "")): r for r in rows}
        for c in cons:
            row = by_code.get(str(c.get("code", "")))
            if not row:
                continue
            pct = row.get("涨跌幅(%)")
            if pct is None:
                continue
            pct = float(pct)
            if abs(pct) >= LEADER_GAP:
                hot_leaders.append(f"{c.get('name')}{pct:+.1f}%")

    triggered = bool(reasons or hot_leaders)
    lines: list[str] = []
    if triggered:
        lines.append(f"【竞价预警 {datetime.now().strftime('%m/%d %H:%M')}】")
        if gap is not None:
            lines.append(f"上证：今开{quote.get('今开')} 昨收{quote.get('昨收')} ({gap:+.2f}%)")
        if reasons:
            lines.append("触发：" + "；".join(reasons))
        if themes:
            lines.append("昨晚主线：" + " | ".join(themes))
        if hot_leaders:
            lines.append("龙头异动：" + " | ".join(hot_leaders))
        hint = _auction_hint(gap, themes)
        if hint:
            lines.append(f"IF：{hint}")

    return {"kind": "auction", "triggered": triggered, "lines": lines}


def check_exhaustion(sectors_path: str | None) -> dict:
    sectors = _load_sectors(sectors_path)
    if not sectors:
        return {"kind": "exhaustion", "triggered": False, "lines": [], "error": "no_sectors_snapshot"}

    top3 = [s.get("industry", "") for s in sectors.get("top_sectors_by_fund_flow", [])[:3] if s.get("industry")]
    fund = _run("fetch_industry_fund_flow.py", "--limit", "10", "--json")
    items = fund.get("items", fund) if isinstance(fund, dict) else fund
    top10 = {str(it.get("industry", "")) for it in (items or [])[:10]}

    dropped = [ind for ind in top3 if ind and not _in_top10(ind, top10)]

    pullbacks: list[str] = []
    for c in sectors.get("consecutive_limit_leaders", [])[:5]:
        code = c.get("code")
        if not code:
            continue
        q = _run("fetch_realtime.py", "--quote", str(code), "--json")
        high = float(q.get("最高") or 0)
        latest = float(q.get("最新价") or 0)
        if high <= 0 or latest <= 0:
            continue
        pb = (high - latest) / high * 100
        if pb >= PULLBACK:
            pullbacks.append(f"{c.get('name')}回撤{pb:.1f}%")

    triggered = bool(dropped or pullbacks)
    lines: list[str] = []
    if triggered:
        lines.append(f"【主题衰竭 {datetime.now().strftime('%m/%d %H:%M')}】")
        if top3:
            lines.append("今早主线：" + " | ".join(top3))
        if dropped:
            lines.append("资金退潮：" + " ".join(f"↓{x}" for x in dropped))
        if pullbacks:
            lines.append("龙头回撤：" + " | ".join(pullbacks))
        lines.append("IF：不追、持仓考虑减或止盈")

    return {"kind": "exhaustion", "triggered": triggered, "lines": lines}


def main() -> None:
    parser = argparse.ArgumentParser(description="P1 conditional premarket alerts")
    parser.add_argument("mode", choices=["auction", "exhaustion"])
    parser.add_argument("--sectors", help="Prior sector snapshot JSON path")
    args = parser.parse_args()

    if args.mode == "auction":
        result = check_auction(args.sectors)
    else:
        result = check_exhaustion(args.sectors)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
