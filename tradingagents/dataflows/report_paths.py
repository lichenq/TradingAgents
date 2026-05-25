"""Filesystem paths for analysis report bundles: 股票名称-股票代码-日期."""

from __future__ import annotations

import re
from pathlib import Path

from tradingagents.dataflows.sector_queries import fetch_sector_payload
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.market import is_cn_ticker, normalize_a_share_code

_INVALID_FS = re.compile(r'[/\\:*?"<>|\n\r\t]+')


def sanitize_report_label(value: str, *, max_len: int = 32) -> str:
    text = _INVALID_FS.sub("_", (value or "").strip())
    text = text.strip("._ ")
    if not text:
        return "未知"
    return text[:max_len]


def resolve_stock_display_name(ticker: str) -> str:
    """Chinese short name from a-share-data sector info, else empty."""
    payload = fetch_sector_payload(ticker)
    if not payload:
        return ""
    return (payload.get("name") or payload.get("security_name") or "").strip()


def report_code_for_ticker(ticker: str) -> str:
    """6-digit code for A-shares; validated ticker symbol otherwise."""
    if is_cn_ticker(ticker):
        code6 = normalize_a_share_code(ticker)
        if code6.isdigit() and len(code6) == 6:
            return code6
    return safe_ticker_component(ticker)


def build_report_bundle_name(ticker: str, trade_date: str) -> str:
    """``长电科技-600584-2026-05-23`` style directory / archive label."""
    code = report_code_for_ticker(ticker)
    name = resolve_stock_display_name(ticker)
    if not name:
        name = code
    date_s = str(trade_date).strip()[:10]
    return f"{sanitize_report_label(name)}-{sanitize_report_label(code)}-{date_s}"


def report_bundle_dir(results_dir: str | Path, ticker: str, trade_date: str) -> Path:
    return Path(results_dir) / build_report_bundle_name(ticker, trade_date)
