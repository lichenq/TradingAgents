#!/usr/bin/env python3
"""
Verify TradingAgents HK stock data routing and AkShare-based fetching.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tradingagents.dataflows.a_share import (
    get_a_share_stock_data,
    get_a_share_indicators,
    get_a_share_fundamentals,
    get_a_share_news,
)


def main():
    ticker = "0700.HK"
    print(f"=== VERIFYING HK AKSHARE ROUTING FOR TICKER: {ticker} ===")
    
    print("\n--- 1. Testing get_a_share_stock_data (OHLCV) ---")
    try:
        ohlcv = get_a_share_stock_data(ticker, "2026-05-15", "2026-05-29")
        print("Success! First 350 chars of output:")
        print(ohlcv[:350])
        print("...")
        print("Last 200 chars of output:")
        print(ohlcv[-200:])
    except Exception as e:
        print(f"FAILED: {e}")
        
    print("\n--- 2. Testing get_a_share_indicators (RSI) ---")
    try:
        rsi = get_a_share_indicators(ticker, "rsi", "2026-05-29", 5)
        print("Success! Indicator output:")
        print(rsi)
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n--- 3. Testing get_a_share_fundamentals ---")
    try:
        fundamentals = get_a_share_fundamentals(ticker, "2026-05-29")
        print("Success! Fundamentals output:")
        print(fundamentals)
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n--- 4. Testing get_a_share_news ---")
    try:
        news = get_a_share_news(ticker, "2026-05-15", "2026-05-29")
        print("Success! First 400 chars of News output:")
        print(news[:400])
        print("...")
    except Exception as e:
        print(f"FAILED: {e}")


if __name__ == "__main__":
    main()
