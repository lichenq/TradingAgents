# tradingagents/agents/utils/market_regime.py
"""Market regime detection — Tuige five-tier system for CN A-shares."""

from __future__ import annotations

import logging
from typing import List, Optional

from tradingagents.dataflows.config import get_config

logger = logging.getLogger(__name__)

# Backward-compatible aliases (deprecated)
HIGH_HEAT_REGIME = "aggressive"
DEFENSIVE_REGIME = "defensive"
NORMAL_REGIME = "rotation"

TUIGE_REGIMES = (
    "aggressive",
    "rotation",
    "pullback_only",
    "defensive",
    "no_trade",
)


def _is_cn_market() -> bool:
    profile = (get_config().get("market_profile") or "us").strip().lower()
    return profile in ("cn", "a", "a_share", "china")


def detect_market_regime(ticker: str, trade_date: str) -> str:
    """Return Tuige regime for CN; neutral ``rotation`` for non-CN tickers."""
    if not _is_cn_market():
        return "rotation"

    from tradingagents.tuige.context import build_tuige_context, tuige_enabled
    from tradingagents.tuige.market_inputs import fetch_tuige_market_inputs

    if not tuige_enabled():
        return "rotation"

    market = fetch_tuige_market_inputs(trade_date)
    ctx = build_tuige_context(
        trade_date,
        ticker=ticker or None,
        quotes=market.quotes,
        index_payload=market.index_payload,
        industry_flows=market.industry_flows,
    )
    return ctx.effective_regime


def detect_book_regime(trade_date: str, quotes: Optional[List] = None) -> str:
    """Book-level Tuige regime (recommend pipeline)."""
    from tradingagents.tuige.context import build_tuige_context, tuige_enabled
    from tradingagents.tuige.market_inputs import fetch_tuige_market_inputs

    if not tuige_enabled() or not _is_cn_market():
        return "rotation"

    market = fetch_tuige_market_inputs(trade_date, quotes=quotes)
    ctx = build_tuige_context(
        trade_date,
        quotes=quotes or market.quotes,
        index_payload=market.index_payload,
        industry_flows=market.industry_flows,
    )
    return ctx.effective_regime


def get_regime_prompt_instructions(regime: str) -> str:
    from tradingagents.tuige.prompt_blocks import get_regime_prompt_instructions as _tuige_prompt

    # Map legacy names if any caller still uses them
    legacy = {
        "HIGH_HEAT_REGIME": "aggressive",
        "DEFENSIVE_REGIME": "defensive",
        "NORMAL_REGIME": "rotation",
    }
    normalized = legacy.get(regime, regime)
    return _tuige_prompt(normalized)


# Retained for sector name lookup used elsewhere (rotation forecast overrides in old code removed from detect path)
def fetch_boards_summary_raw():
    """获取当天全市场行业板块的成交额与涨跌幅快照"""
    import json
    import os
    import urllib.request

    url = "https://dang-invest.com/api/market/boards/summary?mode=industry&limit=120"
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    try:
        req = urllib.request.Request(url)
        proxy_support = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_support)
        with opener.open(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("data", {}).get("items", [])
    except Exception as e:
        logger.warning("Failed to fetch boards summary: %s", e)
        return []


def get_ticker_sector_name(ticker: str) -> str:
    from tradingagents.market import normalize_a_share_code
    from tradingagents.dataflows.sector_queries import fetch_sector_payload

    code6 = normalize_a_share_code(ticker)
    try:
        payload = fetch_sector_payload(ticker)
        if payload and isinstance(payload, dict):
            return (payload.get("industry") or "").strip()
    except Exception as e:
        logger.warning("Failed to fetch sector for %s: %s", ticker, e)
    return ""
