"""Per-ticker industry queries for ``get_global_news`` (CN A-shares)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from tradingagents.dataflows.a_share_runner import run_script
from tradingagents.market import effective_market_profile, is_cn_ticker, normalize_a_share_code


def merge_news_queries(config: dict) -> List[str]:
    """Build the query list for ``get_global_news`` according to ``global_news_mode``.

    - ``macro_plus_ticker`` (CN default): ``global_news_queries`` + ``ticker_news_queries``
    - ``macro_only``: base macro list only
    - ``ticker_only``: industry/ticker queries only; falls back to macro if empty
    """
    mode = (config.get("global_news_mode") or "macro_plus_ticker").strip().lower()
    base = list(config.get("global_news_queries") or [])
    extra = list(config.get("ticker_news_queries") or [])

    if mode == "macro_only":
        candidates = base
    elif mode == "ticker_only":
        candidates = extra if extra else base
    else:
        candidates = base + extra

    seen: set[str] = set()
    merged: List[str] = []
    for q in candidates:
        text = (q or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def industry_to_search_queries(
    industry: str,
    *,
    name: str = "",
    code6: str = "",
) -> List[str]:
    """Turn 东财行业名 into CN news keyword strings (DangInvest / 东财过滤用)."""
    industry = (industry or "").strip()
    if not industry:
        return []

    queries = [
        f"A股 {industry} 板块 政策 龙头",
        f"A股 {industry} 行业 景气 业绩 估值",
    ]
    clean_name = (name or "").strip()
    if clean_name and len(clean_name) <= 12:
        queries.append(f"A股 {clean_name} {industry}")
    if code6:
        queries.append(f"A股 {code6} {industry}")
    return queries


def fetch_sector_payload(ticker: str, *, timeout: int = 18) -> Optional[Dict[str, Any]]:
    """Fetch industry/name via a-share-data ``fetch_sector_info.py``."""
    code6 = normalize_a_share_code(ticker)
    if not code6.isdigit() or len(code6) != 6:
        return None

    ok, _raw, data = run_script(
        "fetch_sector_info.py",
        ["--no-concepts", "--json", code6],
        timeout=timeout,
    )
    if not ok or data is None:
        return None

    if isinstance(data, dict):
        if "results" in data and isinstance(data["results"], list) and data["results"]:
            first = data["results"][0]
            return first if isinstance(first, dict) else None
        if "industry" in data or "name" in data:
            return data
    return None


def resolve_ticker_news_queries(ticker: str, config: dict) -> List[str]:
    """Build extra ``global_news`` search strings for this ticker (CN only)."""
    market = effective_market_profile(ticker, config)
    if market != "cn" and not is_cn_ticker(ticker):
        return []

    payload = fetch_sector_payload(ticker)
    if not payload:
        return []

    industry = (payload.get("industry") or "").strip()
    name = (payload.get("name") or "").strip()
    code6 = normalize_a_share_code(ticker)
    queries = industry_to_search_queries(industry, name=name, code6=code6)
    if industry:
        return queries
    if name:
        return [f"A股 {name} 公司 公告 业绩"]
    return []


def apply_ticker_news_queries(ticker: str, config: dict) -> dict:
    """Return config copy with ``ticker_news_queries`` set for this run."""
    updated = dict(config)
    updated["company_of_interest"] = ticker
    updated["ticker_news_queries"] = resolve_ticker_news_queries(ticker, config)
    return updated
