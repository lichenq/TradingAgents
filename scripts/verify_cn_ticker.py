#!/usr/bin/env python3
"""Quick CN ticker verification (data + optional LLM smoke)."""

from __future__ import annotations

import argparse
import os
import sys

# Ensure project root on path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", default="600584", help="A-share code or Yahoo symbol")
    parser.add_argument("--name", default="长电科技")
    parser.add_argument("--date", default="2026-05-23", help="Trade date YYYY-MM-DD")
    parser.add_argument("--llm-smoke", action="store_true", help="Run DeepSeek structured-output smoke")
    args = parser.parse_args()

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.dataflows.config import set_config
    from tradingagents.dataflows.sector_queries import (
        merge_news_queries,
        resolve_ticker_news_queries,
    )
    from tradingagents.dataflows.cn_sentiment import (
        fetch_events_block,
        fetch_xueqiu_block,
    )
    from tradingagents.dataflows.interface import route_to_vendor
    from tradingagents.market import to_yahoo_a_share_symbol

    ticker = args.code if "." in args.code else to_yahoo_a_share_symbol(args.code)
    config = DEFAULT_CONFIG.copy()
    config["market_profile"] = "cn"
    config["llm_provider"] = "deepseek"
    config["deep_think_llm"] = "deepseek-v4-pro"
    config["quick_think_llm"] = "deepseek-v4-flash"
    config["output_language"] = "Chinese"
    from tradingagents.default_config import apply_market_profile

    apply_market_profile(config)
    config["ticker_news_queries"] = resolve_ticker_news_queries(ticker, config)
    set_config(config)

    print(f"=== CN verify: {args.name} ({ticker}) @ {args.date} ===\n")
    print(f"ticker_news_queries ({len(config['ticker_news_queries'])}):")
    for q in config["ticker_news_queries"]:
        print(f"  - {q}")
    print(f"\nmerged global_news_queries ({len(merge_news_queries(config))}) total\n")

    start = "2026-05-01"
    end = args.date
    print("--- get_stock_data (a_share) ---")
    stock = route_to_vendor("get_stock_data", ticker, start, end)
    print(stock[:800] + ("..." if len(stock) > 800 else ""))
    print(f"\nrecords hint: {'Total records' in stock}\n")

    print("--- get_indicators rsi (a_share) ---")
    ind = route_to_vendor("get_indicators", ticker, "rsi", args.date, 10)
    print(ind[:600], "\n")

    print("--- xueqiu block ---")
    print(fetch_xueqiu_block(ticker, size=5)[:1200], "\n")

    print("--- events/sentiment block (preview) ---")
    print(fetch_events_block(ticker, limit=10)[:1500], "\n")

    if args.llm_smoke:
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key or key.startswith("placeholder"):
            print("SKIP llm-smoke: DEEPSEEK_API_KEY not set")
            return 0
        print("--- DeepSeek structured-output smoke ---")
        import subprocess

        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts/smoke_structured_output.py"), "deepseek"],
            env=os.environ.copy(),
        )
        return r.returncode

    print("OK: data layer checks passed (add --llm-smoke for LLM)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
