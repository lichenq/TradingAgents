#!/usr/bin/env python3
"""Format entry-day scan for WeChat."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def _row(x: dict, *, days: bool = False) -> str:
    code = x.get("代码", "")
    name = x.get("名称") or ""
    pct = x.get("今日涨跌%")
    main = x.get("主力最近%") or x.get("主力最佳%")
    kind = x.get("买点类型") or ""
    tail = ""
    if kind:
        tail += f" [{kind}]"
    if pct is not None:
        tail += f" 今{pct:+.1f}%"
    if main is not None:
        tail += f" 主力{main:+.1f}%"
    if days and x.get("days_in_pool") is not None:
        tail += f" D{x['days_in_pool']}"
    return f"  · {code} {name}{tail}"


def format_prepump(data: dict, *, morning: bool = False) -> str:
    date = data.get("date") or datetime.now().strftime("%Y%m%d")
    wl = data.get("watchlist_delta") or {}
    pool = wl.get("watchlist") or []
    added = wl.get("added") or []
    removed = wl.get("removed") or []
    items = data.get("candidates") or []
    entries = [x for x in items if x.get("买点")]
    watch_b = [x for x in items if x.get("评级") == "B" and not x.get("买点")]

    if morning:
        pending = [x for x in pool if x.get("entry_date") and int(x.get("days_in_pool", 0)) <= 2]
        lines = [f"☀️ 买点执行提醒 {date}", f"昨日确认{len(pending)}只 · 今日竞价/开盘执行"]
        if pending:
            lines.append("\n▎待执行（昨已出买点信号）")
            lines.extend(_row(x, days=True) for x in pending[:6])
        else:
            lines.append("\n无待执行买点，观望。")
        lines.append("\n▎执行纪律")
        lines.append("  · 平开~小幅高开可试；大幅低开破支撑放弃")
        lines.append("  · 已持仓看是否破入场低点")
        msg = "\n".join(lines)
        return msg[:1800] + ("…" if len(msg) > 1800 else "")

    phase = data.get("scan_phase") or ""
    phase_note = "（尾盘·可当即介入）" if phase == "尾盘" else ("（收盘复核）" if phase == "收盘" else "")
    lines = [f"📊 买点扫描 {date}{phase_note}", "识别今日是否为介入日"]
    if entries:
        lines.append(f"\n▎今日买点确认（{len(entries)}只）")
        if phase == "尾盘":
            lines.append("  → 14:35信号：可尾盘轻仓，不必等收盘")
        else:
            lines.append("  → 可尾盘轻仓或明日竞价，不追已涨停")
        lines.extend(_row(x) for x in entries[:8])
    if watch_b:
        lines.append(f"\n▎观察中（等启动日，非买点）")
        lines.extend(_row(x) for x in watch_b[:5])
    if added:
        lines.append("\n▎新进持仓跟踪")
        lines.extend(_row(x) for x in added[:5])
    if removed:
        lines.append("\n▎剔除")
        for x in removed[:4]:
            lines.append(f"  · {x.get('代码')} {x.get('名称','')} ({x.get('剔除原因','')})")
    if pool:
        lines.append("\n▎持仓跟踪中")
        lines.extend(_row(x, days=True) for x in pool[:6])
    if not entries and not added and not pool:
        lines.append("\n今日无买点确认，继续观望。")
    lines.append("\n▎说明")
    lines.append("  · A+买点=类似长电6/17（+4~8%+主力+强势收）")
    lines.append("  · 涨停日不算买点；错过就等下一次结构")
    msg = "\n".join(lines)
    return msg[:1800] + ("…" if len(msg) > 1800 else "")


def main() -> None:
    morning = "--morning" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: prepump_notify_format.py [--morning] <scan.json>", file=sys.stderr)
        sys.exit(1)
    data = json.loads(Path(args[0]).read_text())
    if morning and not data.get("watchlist_delta"):
        wl_path = Path(args[0]).parent / "watchlist.json"
        if wl_path.is_file():
            store = json.loads(wl_path.read_text())
            items = list((store.get("items") or {}).values())
            data["watchlist_delta"] = {"watchlist": items, "pool_size": len(items), "added": [], "removed": []}
    print(format_prepump(data, morning=morning))


if __name__ == "__main__":
    main()
