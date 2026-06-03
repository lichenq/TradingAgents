"""A-share sentiment blocks via a-share-data skill (雪球 + 事件舆情 + 新闻)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from tradingagents.dataflows.a_share_runner import run_script
from tradingagents.market import normalize_a_share_code


def fetch_xueqiu_block(ticker: str, *, size: int = 20) -> str:
    code6 = normalize_a_share_code(ticker)
    from tradingagents.dataflows.cn_prefetch import get_prefetched

    cached = get_prefetched(f"xueqiu:{code6}")
    if cached:
        return cached
    ok, raw, data = run_script(
        "fetch_xueqiu_status.py",
        ["--code", code6, "--format", "json"],
        timeout=15,
    )
    if not ok or not isinstance(data, dict):
        return raw if raw else "<xueqiu unavailable>"

    # Reuse formatter from skill when available
    try:
        from pathlib import Path
        import sys

        skill_scripts = Path.home() / ".cursor/skills/a-share-data/scripts"
        if str(skill_scripts) not in sys.path:
            sys.path.insert(0, str(skill_scripts))
        from fetch_xueqiu_status import format_prompt_block  # type: ignore

        return format_prompt_block(data)
    except Exception:
        return _format_xueqiu_fallback(data)


def _format_xueqiu_fallback(payload: Dict[str, Any]) -> str:
    if not payload.get("ok"):
        return f"<xueqiu unavailable: {payload.get('error', 'unknown')}>"
    posts = payload.get("posts") or []
    if not posts:
        return f"<no Xueqiu posts for {payload.get('symbol', '?')}>"
    lines = [f"Symbol: {payload.get('symbol')} · 雪球讨论 {len(posts)} 条", ""]
    for i, p in enumerate(posts, 1):
        lines.append(
            f"{i}. [{p.get('time', '')} · @{p.get('user', '?')}] {p.get('text', '')}"
        )
    return "\n".join(lines)


def fetch_events_block(ticker: str, *, limit: int = 30) -> str:
    code6 = normalize_a_share_code(ticker)
    from tradingagents.dataflows.cn_prefetch import get_prefetched

    cached = get_prefetched(f"events:{code6}")
    if cached:
        return cached
    ok, raw, data = run_script(
        "fetch_stock_events.py",
        ["--code", code6, "--limit", str(limit), "--json"],
        timeout=55,
    )
    if not ok or not isinstance(data, dict):
        return raw if raw else "<a_share events unavailable>"

    return _format_events_payload(data)


def _format_events_payload(payload: Dict[str, Any]) -> str:
    code = payload.get("code", "")
    name = payload.get("name") or ""
    lines = [f"## A股事件与舆情 · {code} {name}".strip(), ""]

    for section, title in (
        ("performance", "业绩/预告"),
        ("holder_change_buyback", "增减持/回购"),
        ("regulatory", "监管"),
        ("major_contracts", "重大合同/新闻"),
        ("sentiment", "舆情热度"),
    ):
        block = payload.get(section) or {}
        if not isinstance(block, dict):
            continue
        records = []
        for key in ("forecast", "express", "financial_abstract", "records", "rank_snapshot", "rank_trend", "baidu_hot"):
            val = block.get(key)
            if isinstance(val, list) and val:
                records.extend(val[:8])
        count = block.get("count", len(records))
        direction = block.get("direction")
        header = f"### {title} ({count} 条)"
        if direction:
            header += f" · 方向: {direction}"
        lines.append(header)
        if not records:
            lines.append("(无数据)")
        else:
            for rec in records[:6]:
                if isinstance(rec, dict):
                    snippet = " | ".join(
                        f"{k}: {v}" for k, v in list(rec.items())[:6] if v not in (None, "")
                    )
                    lines.append(f"- {snippet[:400]}")
                else:
                    lines.append(f"- {rec}")
        lines.append("")

    return "\n".join(lines).strip()


def fetch_cn_news_block(ticker: str, start_date: str, end_date: str) -> str:
    """Company news via events script (东财新闻字段) + optional market headline filter."""
    code6 = normalize_a_share_code(ticker)
    ok, raw, data = run_script(
        "fetch_stock_events.py",
        ["--code", code6, "--limit", "25", "--json"],
        timeout=55,
    )
    if ok and isinstance(data, dict):
        contracts = data.get("major_contracts") or {}
        rows: List[Any] = []
        if isinstance(contracts, dict):
            rows = contracts.get("records") or contracts.get("news") or []
        if rows:
            lines = [
                f"## {code6} 新闻与公告 ({start_date} 至 {end_date})",
                "",
            ]
            for rec in rows[:20]:
                if isinstance(rec, dict):
                    title = rec.get("新闻标题") or rec.get("title") or rec.get("标题") or ""
                    pub = rec.get("发布时间") or rec.get("date") or rec.get("时间") or ""
                    src = rec.get("文章来源") or rec.get("source") or ""
                    summary = rec.get("新闻内容") or rec.get("content") or rec.get("摘要") or ""
                    lines.append(f"### {title} ({pub}) [{src}]")
                    if summary:
                        lines.append(str(summary)[:500])
                    lines.append("")
            return "\n".join(lines).strip()

    return raw if raw else f"No A-share news blocks for {code6} between {start_date} and {end_date}"
