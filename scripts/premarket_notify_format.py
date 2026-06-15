#!/usr/bin/env python3
"""Format premarket summaries for WeChat (mobile-friendly layout)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

TITLE_EMOJI = {"evening": "🌙", "open": "🔔", "test": "🧪"}
SECTION_EMOJI = {
    "情绪": "🔥",
    "轮动": "🔄",
    "明日动作": "🎯",
    "新闻前瞻": "📰",
    "资金主线": "💰",
    "连板": "🚀",
    "信号": "⚡",
}


def _clip(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _fmt_stock(name: str, pct: float | None = None, rating: str | None = None) -> str:
    name = (name or "").strip()
    base = name
    if pct is not None:
        sign = "+" if float(pct) >= 0 else ""
        base = f"{name} {sign}{float(pct):.1f}%"
    if rating:
        return f"{base}[{rating}]"
    return base


def _sector_head(s: dict[str, Any]) -> str:
    ind = s.get("industry") or "-"
    flow = s.get("main_net_inflow_yi")
    chg = s.get("change_pct")
    rank = s.get("rank") or "?"
    head = f"{rank}. {ind}"
    if flow is not None:
        head += f"  流入{flow}亿"
    if chg is not None:
        sign = "+" if float(chg) >= 0 else ""
        head += f"  {sign}{float(chg):.1f}%"
    fc = s.get("forecast") or {}
    if fc.get("category_label"):
        head += f"  · {fc['category_label']}"
    return head


def _section(title: str, *, first: bool = False) -> str:
    prefix = "\n" if first else "\n\n"
    emoji = SECTION_EMOJI.get(title, "")
    label = f"{emoji} {title}" if emoji else title
    return f"{prefix}▎{label}"


def _bullet(line: str) -> str:
    return f"  · {line}"


def _sector_has_signal(s: dict[str, Any]) -> bool:
    if s.get("limit_up_leaders"):
        return True
    if s.get("board_picks"):
        return True
    if s.get("ta_pullback"):
        return True
    return False


def _sector_is_focus(s: dict[str, Any]) -> bool:
    if s.get("limit_up_leaders"):
        return True
    picks = s.get("board_picks") or []
    return any(float(p.get("change_pct") or 0) >= 5 for p in picks)


def _format_sector_block(s: dict[str, Any]) -> list[str]:
    lines = [_sector_head(s)]
    leaders = s.get("limit_up_leaders") or []
    if leaders:
        names = "、".join(_fmt_stock(x.get("name", "")) for x in leaders[:2])
        lines.append(_bullet(f"🔴 涨停 {names}"))

    picks = s.get("board_picks") or []
    if picks:
        names = "、".join(
            _fmt_stock(x.get("name", ""), x.get("change_pct"), x.get("deep_rating"))
            for x in picks[:2]
        )
        lines.append(_bullet(f"📈 强股 {names}"))

    ta = s.get("ta_pullback") or []
    if ta:
        names = "、".join(
            _fmt_stock(x.get("name", ""), None, x.get("deep_rating")) for x in ta[:2]
        )
        lines.append(_bullet(f"↩️ 回踩 {names}"))
    return lines


def format_rotation_mainline(
    sectors: list[dict[str, Any]], *, primary_limit: int = 3
) -> list[str]:
    if not sectors:
        return []

    shown: list[dict[str, Any]] = []
    shown_inds: set[str] = set()
    for s in sectors:
        if not _sector_has_signal(s):
            continue
        ind = s.get("industry") or ""
        if ind in shown_inds:
            continue
        shown.append(s)
        shown_inds.add(ind)
        if len(shown) >= primary_limit:
            break

    lines: list[str] = []
    for s in shown:
        lines.extend(_format_sector_block(s))

    for s in sectors[3:5]:
        ind = s.get("industry") or ""
        if ind in shown_inds:
            continue
        if not s.get("limit_up_leaders"):
            continue
        lines.extend(_format_sector_block(s))
        shown_inds.add(ind)

    empty_top = [
        s.get("industry")
        for s in sectors[:primary_limit]
        if s.get("industry") and not _sector_has_signal(s)
    ]
    if empty_top:
        lines.append(_bullet(f"⏸️ 仅搭台（无票）: {'、'.join(empty_top)}"))
    return lines


def _tomorrow_action_line(data: dict[str, Any]) -> str:
    sectors = data.get("top_sectors_by_fund_flow") or []
    cat = data.get("news_catalyst") or {}
    insight = data.get("llm_insight") or {}

    focus: list[str] = []
    for s in sectors:
        ind = s.get("industry") or ""
        if not ind or not _sector_is_focus(s):
            continue
        focus.append(ind)
        if len(focus) >= 2:
            break

    top3_inds = {s.get("industry") for s in sectors[:3]}
    watch: list[str] = []
    for ind in cat.get("ahead_of_fund_flow") or []:
        if ind and ind not in top3_inds and ind not in watch:
            watch.append(ind)
    if not watch:
        for p in insight.get("predicted_sectors") or []:
            ind = p.get("industry") or ""
            if ind and ind not in top3_inds and ind not in watch:
                watch.append(ind)

    scaffold = [
        s.get("industry")
        for s in sectors[:3]
        if s.get("industry") and not _sector_has_signal(s)
    ]

    parts: list[str] = []
    if focus:
        parts.append(f"主盯 {' / '.join(focus)}")
    if watch:
        parts.append(f"观察 {' / '.join(watch[:3])}")
    if scaffold:
        parts.append(f"搭台 {' / '.join(scaffold[:2])}")
    return " · ".join(parts)


def _news_body(cat: dict[str, Any], insight: dict[str, Any] | None = None) -> list[str]:
    pred = cat.get("predicted_sectors") or []
    llm_pred = cat.get("llm_predicted") or (insight or {}).get("predicted_sectors") or []
    if not pred and not llm_pred:
        return []
    lines: list[str] = []
    if pred:
        tops = "  ".join(f"{p.get('industry')}({p.get('article_count', 0)})" for p in pred[:3])
        lines.append(_bullet(tops))
    for s in llm_pred[:2]:
        reason = _clip(s.get("reason") or "", 28)
        conf = s.get("confidence") or ""
        tag = f" [{conf}]" if conf else ""
        lines.append(_bullet(f"🤖 {s.get('industry')}{tag} — {reason}"))
    ahead = cat.get("ahead_of_fund_flow") or []
    if ahead:
        lines.append(_bullet(f"👀 观察 → {' / '.join(ahead[:3])}"))
    watch = cat.get("llm_watch") or (insight or {}).get("watch") or ""
    if watch:
        lines.append(_bullet(f"🎯 {_clip(watch, 36)}"))
    elif pred:
        hl = (pred[0].get("headlines") or [""])[0]
        if hl:
            lines.append(_bullet(f"📌 {_clip(hl, 32)}"))
    return lines


def _tomorrow_action_body(data: dict[str, Any]) -> list[str]:
    action = _tomorrow_action_line(data)
    if not action:
        return []
    return [_bullet(action)]


def _rotation_body(d: dict[str, Any], *, kind: str) -> list[str]:
    delta = d.get("delta_vs_previous") or {}
    confirmed = d.get("catalyst_confirmed") or []
    lines: list[str] = []

    if delta.get("narrative"):
        lines.append(_bullet(delta["narrative"]))
    elif kind == "open":
        ups = delta.get("rank_up") or []
        downs = delta.get("exit_top") or []
        if downs:
            lines.append(_bullet(f"⬇️ 退出 {' / '.join(downs[:2])}"))
        if ups:
            lines.append(_bullet(f"⬆️ 上升 {' / '.join(x['industry'] for x in ups[:2])}"))

    if confirmed:
        lines.append(_bullet(f"✅ 催化确认 {' / '.join(confirmed[:3])}"))

    fc = d.get("sector_rotation_forecast") or {}
    for h in (fc.get("highlights") or [])[:2]:
        ind = h.get("industry") or ""
        label = h.get("category_label") or h.get("category") or ""
        prob = h.get("probability") or ""
        if ind:
            lines.append(_bullet(f"🔮 {ind} {label} {prob}".strip()))
    return lines


def _consecutive_body(
    cons: list[dict[str, Any]],
    *,
    limit: int = 3,
    min_boards: int = 2,
    min_pct: float = 0,
) -> list[str]:
    lines: list[str] = []
    for x in cons:
        boards = int(x.get("yesterday_boards") or 0)
        pct = float(x.get("change_pct") or 0)
        if boards < min_boards or pct < min_pct:
            continue
        lines.append(_bullet(f"{x.get('name')} {boards}板  {pct:+.1f}%"))
        if len(lines) >= limit:
            break
    return lines


def _append_section(
    lines: list[str],
    title: str,
    body: list[str],
    *,
    first: bool,
) -> bool:
    if not body:
        return first
    lines.append(_section(title, first=first))
    lines.extend(body)
    return False


def format_footer(kind: str) -> str:
    if kind in ("evening", "test"):
        return "\n\n—\n⏰ 9:35 看资金是否印证「新闻前瞻」"
    if kind == "open":
        return "\n\n—\n💡 盘中只追资金确认后的主线"
    return ""


def format_notify(data: dict[str, Any], kind: str) -> str:
    title_map = {"evening": "盘前夜报", "open": "开盘确认", "test": "盘前测试"}
    title = title_map.get(kind, "盘前")
    ts = datetime.now().strftime("%m/%d %H:%M")

    emoji = TITLE_EMOJI.get(kind, "📊")
    lines = [f"{emoji} 【{title}】{ts}"]
    first = True

    mc = data.get("market_limit_up_count")
    if mc is not None:
        pool = data.get("limit_up_pool_size") or data.get("limit_up_pool_sample_size")
        mood = f"涨停 {mc} 家"
        if pool:
            mood += f"  ·  股池 {pool}"
        first = _append_section(lines, "情绪", [_bullet(f"📊 {mood}")], first=first)

    first = _append_section(lines, "轮动", _rotation_body(data, kind=kind), first=first)

    first = _append_section(lines, "明日动作", _tomorrow_action_body(data), first=first)

    insight = data.get("llm_insight") or {}
    cat = data.get("news_catalyst") or {}
    first = _append_section(lines, "新闻前瞻", _news_body(cat, insight), first=first)

    sectors = data.get("top_sectors_by_fund_flow") or []
    mainline = format_rotation_mainline(sectors)
    if mainline:
        first = _append_section(lines, "资金主线", mainline, first=first)

    cons = data.get("consecutive_limit_leaders") or []
    _append_section(lines, "连板", _consecutive_body(cons), first=first)

    footer = format_footer(kind)
    if footer:
        lines.append(footer)

    return "\n".join(lines)


def format_p1_auction(lines_in: list[str]) -> str:
    if not lines_in:
        return ""
    body = [_bullet(_clip(ln, 40)) for ln in lines_in[1:] if ln.strip()]
    ts = datetime.now().strftime("%m/%d %H:%M")
    parts = [f"⚡ 【竞价预警】{ts}"]
    if body:
        parts.append(_section("信号", first=True))
        parts.extend(body)
    parts.append("\n\n—\n💡 高开追主线 · 低开只观察")
    return "\n".join(parts)


def format_p1_exhaustion(lines_in: list[str]) -> str:
    if not lines_in:
        return ""
    body = [_bullet(_clip(ln, 40)) for ln in lines_in[1:] if ln.strip()]
    ts = datetime.now().strftime("%m/%d %H:%M")
    parts = [f"📉 【主题衰竭】{ts}"]
    if body:
        parts.append(_section("信号", first=True))
        parts.extend(body)
    parts.append("\n\n—\n🛑 不追 · 持仓考虑减")
    return "\n".join(parts)


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: premarket_notify_format.py <kind> <sectors.json>", file=sys.stderr)
        sys.exit(1)
    kind = sys.argv[1]
    data = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    print(format_notify(data, kind))


if __name__ == "__main__":
    main()
