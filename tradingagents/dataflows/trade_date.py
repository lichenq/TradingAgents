"""Default analysis trade_date: today if a session day, else previous session."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Dict, Optional, Set

import pandas as pd

from tradingagents.market import cn_uses_a_share_skill, effective_market_profile

logger = logging.getLogger(__name__)

_CALENDAR_CACHE: Dict[str, Set[str]] = {}


def resolve_default_trade_date(
    ticker: str = "",
    config: Optional[dict] = None,
    *,
    as_of: Optional[datetime] = None,
) -> str:
    """Return YYYY-MM-DD for analysis: calendar today when tradable, else prior session."""
    config = config or {}
    as_of = as_of or datetime.now()
    calendar_day = as_of.date()
    profile = effective_market_profile(ticker, config)

    if profile == "cn" or cn_uses_a_share_skill(ticker, config):
        return _cn_default_trade_date(calendar_day)
    return _us_default_trade_date(calendar_day)


def _us_default_trade_date(calendar_day: date) -> str:
    ts = pd.Timestamp(calendar_day)
    if ts.weekday() < 5:
        last = pd.bdate_range(end=ts, periods=1)
        if len(last) and last[-1].date() == calendar_day:
            return calendar_day.strftime("%Y-%m-%d")
    prev = pd.bdate_range(end=ts - pd.Timedelta(days=1), periods=1)
    return prev[-1].strftime("%Y-%m-%d")


def _cn_trading_days_between(start: date, end: date) -> Set[str]:
    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")
    cache_key = f"{start_s}:{end_s}"
    if cache_key in _CALENDAR_CACHE:
        return _CALENDAR_CACHE[cache_key]

    days: Set[str] = set()
    try:
        from tradingagents.dataflows.a_share_runner import run_script

        ok, _raw, data = run_script(
            "fetch_history_fallback.py",
            ["--trade-dates", "--start", start_s, "--end", end_s, "--json"],
            timeout=30,
        )
        if ok and isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and row.get("date"):
                    days.add(str(row["date"])[:10])
    except Exception as exc:
        logger.warning("CN trade calendar fetch failed: %s", exc)

    if not days:
        cur = start
        while cur <= end:
            if cur.weekday() < 5:
                days.add(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)

    _CALENDAR_CACHE[cache_key] = days
    return days


def _cn_default_trade_date(calendar_day: date) -> str:
    start = calendar_day - timedelta(days=60)
    days = _cn_trading_days_between(start, calendar_day)
    today_s = calendar_day.strftime("%Y-%m-%d")
    if today_s in days:
        return today_s
    prior = sorted(d for d in days if d < today_s)
    if prior:
        return prior[-1]
    return _weekday_fallback(calendar_day)


def _weekday_fallback(calendar_day: date) -> str:
    cur = calendar_day
    while cur.weekday() >= 5:
        cur -= timedelta(days=1)
    return cur.strftime("%Y-%m-%d")


def cn_trading_sessions_after(rec_date: str, as_of: date) -> int:
    """Count A-share sessions strictly after rec_date through as_of (inclusive)."""
    rec_d = datetime.strptime(str(rec_date)[:10], "%Y-%m-%d").date()
    if as_of < rec_d:
        return 0
    days = sorted(_cn_trading_days_between(rec_d, as_of))
    rec_s = rec_d.strftime("%Y-%m-%d")
    as_of_s = as_of.strftime("%Y-%m-%d")
    return len([d for d in days if d > rec_s and d <= as_of_s])
