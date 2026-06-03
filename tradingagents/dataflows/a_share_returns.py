"""Compute holding-period returns from a-share-data K-line scripts (no Yahoo)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from tradingagents.dataflows.a_share_runner import run_script
from tradingagents.market import normalize_a_share_code


def _fetch_kline_closes(code6: str, start_date: str, end_date: str) -> List[Tuple[str, float]]:
    ok, _raw, rows = run_script(
        "fetch_history.py",
        [
            "--kline", code6,
            "--start", start_date,
            "--end", end_date,
            "--freq", "1d",
            "--count", "120",
            "--json",
        ],
        timeout=40,
    )
    if not ok or not isinstance(rows, list):
        return []
    out: List[Tuple[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = str(row.get("time", ""))[:10]
        try:
            close = float(row["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if day:
            out.append((day, close))
    out.sort(key=lambda x: x[0])
    return out


def fetch_raw_and_alpha_returns(
    ticker: str,
    benchmark: str,
    trade_date: str,
    holding_days: int = 5,
) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """Return (raw_return, alpha_return, actual_days) using skill K-lines only."""
    start = datetime.strptime(trade_date, "%Y-%m-%d")
    end = start + timedelta(days=holding_days + 14)
    start_s = trade_date
    end_s = end.strftime("%Y-%m-%d")

    stock_code = normalize_a_share_code(ticker)
    bench_code = normalize_a_share_code(benchmark)

    stock_series = _fetch_kline_closes(stock_code, start_s, end_s)
    bench_series = _fetch_kline_closes(bench_code, start_s, end_s)
    if len(stock_series) < 2 or len(bench_series) < 2:
        return None, None, None

    stock_on = [(d, c) for d, c in stock_series if d >= trade_date]
    bench_on = [(d, c) for d, c in bench_series if d >= trade_date]
    if len(stock_on) < 2 or len(bench_on) < 2:
        return None, None, None

    actual = min(holding_days, len(stock_on) - 1, len(bench_on) - 1)
    if actual < 1:
        return None, None, None

    s0, s1 = stock_on[0][1], stock_on[actual][1]
    b0, b1 = bench_on[0][1], bench_on[actual][1]
    if s0 == 0 or b0 == 0:
        return None, None, None

    raw = (s1 - s0) / s0
    alpha = raw - (b1 - b0) / b0
    return float(raw), float(alpha), int(actual)
