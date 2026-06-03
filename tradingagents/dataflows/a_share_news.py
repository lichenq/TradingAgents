"""A-share news helpers without Yahoo Finance."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List

from dateutil.relativedelta import relativedelta

from tradingagents.dataflows.a_share_runner import run_script
from tradingagents.dataflows.cn_sentiment import fetch_cn_news_block
from tradingagents.dataflows.sector_queries import merge_news_queries
from tradingagents.market import normalize_a_share_code


def _query_terms(query: str) -> List[str]:
    """Extract loose keyword tokens from a CN search query string."""
    text = (query or "").replace("A股", " ")
    parts = re.split(r"[\s、，,/]+", text)
    terms = [p.strip() for p in parts if len(p.strip()) >= 2]
    # Drop ultra-generic tokens that match everything
    stop = {"板块", "行业", "政策", "龙头", "业绩", "估值", "景气"}
    return [t for t in terms if t not in stop]


def _item_text(item: Dict[str, Any]) -> str:
    title = item.get("title") or ""
    content = item.get("content") or ""
    source = item.get("source") or ""
    return f"{title} {content} {source}"


def filter_market_items_by_queries(
    items: Iterable[Dict[str, Any]],
    queries: List[str],
    *,
    max_items: int = 15,
) -> List[Dict[str, Any]]:
    """Keep market-news rows that match any configured query keyword."""
    terms: List[str] = []
    for q in queries:
        terms.extend(_query_terms(q))
    if not terms:
        return list(items)[:max_items]

    matched: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        blob = _item_text(item)
        if any(t in blob for t in terms):
            matched.append(item)
        if len(matched) >= max_items:
            break
    return matched


def format_market_items(
    items: List[Dict[str, Any]],
    *,
    header: str,
    limit: int,
) -> str:
    lines = [header, ""]
    for item in items[:limit]:
        title = item.get("title") or ""
        content = (item.get("content") or "")[:400]
        pub = item.get("published_at") or ""
        source = item.get("source") or "DangInvest"
        lines.append(f"### {title} ({pub}) [{source}]")
        if content:
            lines.append(content)
        lines.append("")
    if len(lines) <= 2:
        return ""
    return "\n".join(lines)
