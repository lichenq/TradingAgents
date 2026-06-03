"""Resolve A-share OHLCV / indicator end dates for live vs historical runs."""

from __future__ import annotations

from datetime import datetime, timedelta


def cn_ohlcv_end_date(trade_date: str, *, now: datetime | None = None) -> str:
    """End date when fetching market data.

    Live runs (trade_date within a week of today, or in the future) request
    through **today** so the last daily bar and realtime quote are as fresh as
    the analysis run. Historical backtests keep ``trade_date`` as the cap.
    """
    now = now or datetime.now()
    today = now.date()
    td = datetime.strptime(str(trade_date)[:10], "%Y-%m-%d").date()
    if td >= today:
        return today.strftime("%Y-%m-%d")
    if (today - td).days <= 7:
        return today.strftime("%Y-%m-%d")
    return str(trade_date)[:10]


def cn_indicator_end_date(trade_date: str, *, now: datetime | None = None) -> str:
    """Upper bound (inclusive) for filtering indicator rows — same as OHLCV end."""
    return cn_ohlcv_end_date(trade_date, now=now)


def is_live_analysis(trade_date: str, *, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    today = now.date()
    td = datetime.strptime(str(trade_date)[:10], "%Y-%m-%d").date()
    if td >= today:
        return True
    return (today - td).days <= 7
