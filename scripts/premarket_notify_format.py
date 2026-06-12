#!/usr/bin/env python3
"""Format premarket summaries for WeChat (mobile-friendly layout)."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

TITLE_EMOJI = {"evening": "🌙", "open": "🔔", "test": "🧪"}
SECTION_EMOJI = {
    "情绪": "🔥",
    "轮动": "🔄",
    "AI要点": "💬",
    "新闻前瞻": "📰",
    "资金主线 TOP3": "💰",
    "连板": "🚀",
    "信号": "⚡",
    "深度精选": "🎯",
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


def format_mainline_sectors(sectors: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for s in sectors[:limit]:
        lines.append(_sector_head(s))

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


def _ai_points_body(insight: dict[str, Any], deep: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    brief = (insight.get("brief") or "").strip()
    if brief:
        parts = [p.strip() for p in re.split(r"[。！？\n；;，,]", brief) if p.strip()]
        if len(parts) == 1:
            lines.append(_bullet(_clip(parts[0], 42)))
        else:
            lines.extend(_bullet(_clip(p, 42)) for p in parts[:2])
    summary = (deep.get("portfolio_summary") or "").strip()
    if summary:
        lines.append(_bullet(f"📊 {_clip(summary, 42)}"))
    for rec in (deep.get("recommended") or [])[:3]:
        name = rec.get("name") or rec.get("code")
        rating = rec.get("reviewed_rating") or rec.get("rating") or ""
        if name:
            tag = f" [{rating}]" if rating else ""
            lines.append(_bullet(f"✅ {name}{tag}"))
    return lines


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


def _consecutive_body(cons: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for x in cons[:limit]:
        pct = float(x.get("change_pct") or 0)
        lines.append(_bullet(f"{x.get('name')} {x.get('yesterday_boards')}板  {pct:+.1f}%"))
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

    insight = data.get("llm_insight") or {}
    deep = data.get("deep_curation") or {}
    first = _append_section(lines, "AI要点", _ai_points_body(insight, deep), first=first)

    cat = data.get("news_catalyst") or {}
    first = _append_section(lines, "新闻前瞻", _news_body(cat, insight), first=first)

    sectors = data.get("top_sectors_by_fund_flow") or []
    if sectors:
        first = _append_section(lines, "资金主线 TOP3", format_mainline_sectors(sectors), first=first)

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
