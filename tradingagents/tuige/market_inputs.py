"""Cached Tuige book-level market inputs (index, breadth, industry flows)."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CN_TZ = timezone(timedelta(hours=8))
_CACHE: Dict[str, tuple[float, "TuigeMarketInputs"]] = {}


@dataclass
class TuigeMarketInputs:
    index_payload: Optional[Dict[str, Any]] = None
    industry_flows: Optional[List[Dict[str, Any]]] = None
    quotes: Optional[List[Dict[str, Any]]] = None


def clear_tuige_market_cache() -> None:
    _CACHE.clear()


def normalize_index_payload(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if isinstance(raw, list):
        return {"data": raw}
    if isinstance(raw, dict):
        return raw
    return None


def _cache_ttl_seconds(now: Optional[datetime] = None) -> int:
    now = now or datetime.now(_CN_TZ)
    if now.weekday() >= 5:
        return 3600
    minutes = now.hour * 60 + now.minute
    if 9 * 60 + 30 <= minutes < 15 * 60:
        return 300
    return 3600


def _cache_key(trade_date: str, *, with_quotes: bool) -> str:
    return f"{trade_date[:10]}:quotes={int(with_quotes)}"


def _read_cache(key: str) -> Optional[TuigeMarketInputs]:
    entry = _CACHE.get(key)
    if not entry:
        return None
    fetched_at, payload = entry
    if time.time() - fetched_at > _cache_ttl_seconds():
        _CACHE.pop(key, None)
        return None
    return payload


def _write_cache(key: str, payload: TuigeMarketInputs) -> TuigeMarketInputs:
    _CACHE[key] = (time.time(), payload)
    return payload


def _fetch_index() -> Optional[Dict[str, Any]]:
    from tradingagents.dataflows.a_share_runner import run_script

    ok, _, idx = run_script("fetch_realtime.py", ["--index", "--json"], timeout=60)
    if not ok:
        return None
    return normalize_index_payload(idx)


def _fetch_industry_flows() -> Optional[List[Dict[str, Any]]]:
    from tradingagents.dataflows.a_share_runner import run_script

    ok, _, flow = run_script(
        "fetch_industry_fund_flow.py",
        ["--limit", "20", "--json"],
        timeout=60,
    )
    if not ok or not isinstance(flow, dict):
        return None
    items = flow.get("items") or flow.get("data") or []
    return items if isinstance(items, list) else None


def _fetch_all_quotes() -> Optional[List[Dict[str, Any]]]:
    from tradingagents.dataflows.a_share_runner import run_script

    ok, _, parsed = run_script(
        "fetch_realtime.py",
        ["--all-quote", "--sort", "amount_desc", "--top", "0", "--json"],
        timeout=120,
    )
    if not ok or not isinstance(parsed, dict):
        return None
    quotes = parsed.get("data") or []
    return quotes if isinstance(quotes, list) else None


def _fetch_index_and_flows() -> TuigeMarketInputs:
    with ThreadPoolExecutor(max_workers=2) as pool:
        idx_f = pool.submit(_fetch_index)
        flow_f = pool.submit(_fetch_industry_flows)
        return TuigeMarketInputs(
            index_payload=idx_f.result(),
            industry_flows=flow_f.result(),
        )


def fetch_tuige_market_inputs(
    trade_date: str,
    *,
    quotes: Optional[List[Dict[str, Any]]] = None,
    include_quotes: bool = True,
) -> TuigeMarketInputs:
    """Fetch index + industry flows, optionally all-market quotes, with process cache."""
    if quotes:
        key = _cache_key(trade_date, with_quotes=False)
        cached = _read_cache(key)
        if cached:
            return TuigeMarketInputs(
                index_payload=cached.index_payload,
                industry_flows=cached.industry_flows,
                quotes=quotes,
            )
        fetched = _fetch_index_and_flows()
        _write_cache(key, fetched)
        return TuigeMarketInputs(
            index_payload=fetched.index_payload,
            industry_flows=fetched.industry_flows,
            quotes=quotes,
        )

    if not include_quotes:
        key = _cache_key(trade_date, with_quotes=False)
        cached = _read_cache(key)
        if cached:
            return cached
        return _write_cache(key, _fetch_index_and_flows())

    key = _cache_key(trade_date, with_quotes=True)
    cached = _read_cache(key)
    if cached:
        return cached

    with ThreadPoolExecutor(max_workers=3) as pool:
        idx_f = pool.submit(_fetch_index)
        flow_f = pool.submit(_fetch_industry_flows)
        quotes_f = pool.submit(_fetch_all_quotes)
        payload = TuigeMarketInputs(
            index_payload=idx_f.result(),
            industry_flows=flow_f.result(),
            quotes=quotes_f.result(),
        )
    return _write_cache(key, payload)
