"""Parallel CN data warm-up before the analyst graph runs."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from tradingagents.dataflows.cn_market_dates import cn_ohlcv_end_date
from tradingagents.market import cn_uses_a_share_skill, normalize_a_share_code

logger = logging.getLogger(__name__)

_PREFETCH_CACHE: Dict[str, str] = {}


def get_prefetched(key: str) -> Optional[str]:
    return _PREFETCH_CACHE.get(key)


def clear_prefetch_cache() -> None:
    _PREFETCH_CACHE.clear()


def _cache(key: str, value: str) -> None:
    if value:
        _PREFETCH_CACHE[key] = value


def run_cn_prefetch(
    ticker: str,
    trade_date: str,
    config: dict,
    *,
    max_workers: int = 4,
) -> List[str]:
    """Warm caches for A-share analysts. Returns short log lines for progress output."""
    if not cn_uses_a_share_skill(ticker, config):
        return []

    max_workers = int(max_workers)
    clear_prefetch_cache()
    code6 = normalize_a_share_code(ticker)
    trade_date = str(trade_date)
    end = cn_ohlcv_end_date(trade_date)
    start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=120)).strftime("%Y-%m-%d")
    news_start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")

    def task_sector() -> Tuple[str, str]:
        from tradingagents.dataflows.sector_queries import fetch_sector_payload

        payload = fetch_sector_payload(ticker)
        if payload:
            name = (payload.get("name") or "").strip()
            ind = (payload.get("industry") or "").strip()
            return "sector", f"{name or code6} · {ind or '行业未知'}"
        return "sector", ""

    def task_fundamentals() -> Tuple[str, str]:
        from tradingagents.dataflows.a_share import get_a_share_fundamentals

        block = get_a_share_fundamentals(ticker, end)
        _cache(f"fundamentals:{code6}", block)
        return "fundamentals", "ok" if block and "unavailable" not in block.lower() else "empty"

    def task_xueqiu() -> Tuple[str, str]:
        from tradingagents.dataflows.cn_sentiment import fetch_xueqiu_block

        block = fetch_xueqiu_block(ticker)
        _cache(f"xueqiu:{code6}", block)
        return "xueqiu", "ok" if block else "empty"

    def task_events() -> Tuple[str, str]:
        from tradingagents.dataflows.cn_sentiment import fetch_events_block

        block = fetch_events_block(ticker, limit=15)
        _cache(f"events:{code6}", block)
        return "events", "ok" if block else "empty"

    def task_kline() -> Tuple[str, str]:
        from tradingagents.dataflows.a_share import _build_a_share_ohlcv_block

        block = _build_a_share_ohlcv_block(ticker, start, trade_date, use_cache=False)
        _cache(f"kline:{code6}", block)
        return "kline", "ok" if block else "empty"

    def task_news() -> Tuple[str, str]:
        from tradingagents.dataflows.config import get_config
        from tradingagents.dataflows.interface import route_to_vendor

        cfg = get_config()
        look_back = int(cfg.get("global_news_lookback_days") or 7)
        article_limit = int(cfg.get("global_news_article_limit") or 10)

        company = route_to_vendor("get_news", ticker, news_start, end)
        # get_global_news(curr_date, look_back_days, limit) — not (ticker, start, end)
        macro = route_to_vendor("get_global_news", end, look_back, article_limit)
        _cache(f"news_company:{code6}", company)
        _cache(f"news_macro:{code6}", macro)
        return "news", "ok"

    jobs = [
        task_sector,
        task_fundamentals,
        task_xueqiu,
        task_events,
        task_kline,
        task_news,
    ]
    workers = max(1, min(max_workers, len(jobs)))
    lines: List[str] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cn-prefetch") as pool:
        futures = [pool.submit(fn) for fn in jobs]
        for fut in as_completed(futures):
            try:
                name, status = fut.result()
                lines.append(f"预取 {name}: {status}")
                logger.info("CN prefetch %s -> %s", name, status)
            except Exception as exc:
                lines.append(f"预取失败: {exc}")
                logger.warning("CN prefetch error: %s", exc)
    return lines
