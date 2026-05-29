#!/usr/bin/env python3
"""Verify Alpha Vantage (free tier) data via TradingAgents vendors."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass


def _preview(text: str, n: int = 120) -> str:
    one_line = " ".join(text.split())
    return one_line[:n] + ("..." if len(one_line) > n else "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Alpha Vantage connectivity check")
    parser.add_argument(
        "--tickers",
        default="NVDA,0700.HK",
        help="Comma-separated symbols (default: NVDA,0700.HK)",
    )
    parser.add_argument("--days", type=int, default=14, help="OHLCV lookback days")
    args = parser.parse_args()

    key = (os.getenv("ALPHA_VANTAGE_API_KEY") or "").strip()
    if not key:
        print("FAIL: ALPHA_VANTAGE_API_KEY is not set.")
        print("Get a free key: https://www.alphavantage.co/support/#api-key")
        print("Then add to .env:  ALPHA_VANTAGE_API_KEY=your_key_here")
        return 2
    if key.lower() == "demo":
        print("FAIL: 'demo' key is not valid for real requests.")
        print("Claim a free personal key at https://www.alphavantage.co/support/#api-key")
        return 2

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.dataflows.alpha_vantage_fundamentals import get_fundamentals
    from tradingagents.dataflows.alpha_vantage_news import get_news
    from tradingagents.dataflows.config import set_config
    from tradingagents.dataflows.interface import route_to_vendor

    config = DEFAULT_CONFIG.copy()
    config["market_profile"] = "us"
    config["data_vendors"] = {
        "core_stock_apis": "alpha_vantage",
        "technical_indicators": "alpha_vantage",
        "fundamental_data": "alpha_vantage",
        "news_data": "alpha_vantage",
    }
    set_config(config)

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]

    print(f"=== Alpha Vantage verify (key len={len(key)}) ===")
    print(f"OHLCV range: {start} .. {end}\n")

    all_ok = True
    for sym in tickers:
        print(f"--- {sym} ---")
        try:
            ohlcv = route_to_vendor("get_stock_data", sym, start, end)
            bad = any(
                x in ohlcv
                for x in (
                    "Error Message",
                    '"Information"',
                    '"Note"',
                    "Invalid API call",
                    "premium endpoint",
                )
            )
            lines = [ln for ln in ohlcv.splitlines() if ln.strip()]
            ok = not bad and len(lines) >= 2
            print(f"  OHLCV: {'OK' if ok else 'FAIL'} ({len(lines)} lines)")
            if ok:
                print(f"    first: {_preview(lines[0])}")
                print(f"    last:  {_preview(lines[-1])}")
            else:
                print(f"    body:  {_preview(ohlcv, 200)}")
                all_ok = False
        except Exception as exc:
            print(f"  OHLCV: FAIL -> {type(exc).__name__}: {exc}")
            all_ok = False

        try:
            fund = get_fundamentals(sym, end)
            if isinstance(fund, dict):
                ok = bool(fund.get("Symbol") or fund.get("Name"))
                print(
                    f"  Fundamentals: {'OK' if ok else 'FAIL'} "
                    f"Name={fund.get('Name', '?')} PE={fund.get('PERatio', 'N/A')}"
                )
                if not ok:
                    all_ok = False
            else:
                ok = "Symbol" in str(fund)
                print(f"  Fundamentals: {'OK' if ok else 'FAIL'} {_preview(str(fund), 160)}")
                if not ok:
                    all_ok = False
        except Exception as exc:
            print(f"  Fundamentals: FAIL -> {type(exc).__name__}: {exc}")
            all_ok = False

        try:
            news = get_news(sym, start, end)
            if isinstance(news, dict):
                count = len(news.get("feed", []))
                print(f"  News: OK ({count} articles)")
            else:
                ok = len(str(news)) > 80
                print(f"  News: {'OK' if ok else 'FAIL'} {_preview(str(news), 120)}")
                if not ok:
                    all_ok = False
        except Exception as exc:
            print(f"  News: FAIL -> {type(exc).__name__}: {exc}")
            all_ok = False
        print()

    if all_ok:
        print("OK: Alpha Vantage data is usable for configured tickers.")
        print("Tip: set TRADINGAGENTS_MARKET=us and data_vendors=alpha_vantage in .env or config.")
        return 0
    print("FAIL: one or more checks failed (quota, symbol, or API error).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
