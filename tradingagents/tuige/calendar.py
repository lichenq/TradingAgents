"""Calendar windows for institutional rebalance observation."""

from __future__ import annotations

from datetime import date, datetime


def parse_trade_date(trade_date: str) -> date:
    return datetime.strptime(trade_date[:10], "%Y-%m-%d").date()


def in_rebalance_calendar_window(trade_date: str) -> bool:
    """True when trade_date falls in a typical institutional rebalance window."""
    d = parse_trade_date(trade_date)
    month, day = d.month, d.day

    # H1 settlement / H2 open: late Jun through early Jul
    if month == 6 and day >= 20:
        return True
    if month == 7 and day <= 10:
        return True

    # Quarter-end ±3 trading days (approximate with calendar days)
    if month in (3, 6, 9, 12) and day >= 25:
        return True
    if month in (1, 4, 7, 10) and day <= 5:
        return True

    return False
