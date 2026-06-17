#!/usr/bin/env python3
"""
Hong Kong Stock Data Fetcher (AkShare-based, completely free and robust)
Bypasses sandbox DNS blocks for Eastmoney major financials using a DNS patch.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta

# Avoid tqdm progress bar pollution in JSON outputs
os.environ["TQDM_DISABLE"] = "1"

# --- Clear active proxies to bypass local IDE interception ---
for key in [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY", "SOCKS5_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "socks_proxy", "socks5_proxy"
]:
    os.environ.pop(key, None)

import dns_patch

dns_patch.apply()


def clean_hk_symbol(sym: str) -> str:
    """Normalize symbol to 5-digit HK stock code, e.g. '0700.HK' -> '00700'."""
    s = (sym or "").strip().upper()
    if s.endswith(".HK"):
        s = s[:-3]
    s = "".join(c for c in s if c.isdigit())
    if s:
        return s.zfill(5)
    return sym


def fetch_ohlcv(symbol: str, start: str, end: str) -> list[dict]:
    """Fetch HK K-line daily history using akshare."""
    import akshare as ak
    import pandas as pd

    clean_sym = clean_hk_symbol(symbol)
    try:
        # Convert start/end to YYYYMMDD required by akshare
        s_dt = datetime.strptime(start, "%Y-%m-%d").strftime("%Y%m%d")
        e_dt = datetime.strptime(end, "%Y-%m-%d").strftime("%Y%m%d")

        df = ak.stock_hk_hist(
            symbol=clean_sym,
            period="daily",
            start_date=s_dt,
            end_date=e_dt,
            adjust="qfq"
        )
        if df is None or df.empty:
            return []

        col_map = {
            "日期": "time",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "涨跌幅": "pctChg"
        }
        # Rename columns and convert to list of dicts
        df = df.rename(columns=col_map)
        valid_cols = [c for c in col_map.values() if c in df.columns]
        df = df[valid_cols].copy()
        
        # Format time column to YYYY-MM-DD
        df["time"] = pd.to_datetime(df["time"]).dt.strftime("%Y-%m-%d")
        
        # Round numerical values
        num_cols = ["open", "high", "low", "close", "pctChg"]
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").round(2)
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype(int)

        return df.to_dict(orient="records")
    except Exception as exc:
        print(f"Error fetching OHLCV K-lines: {exc}", file=sys.stderr)
        return []


def fetch_indicators(symbol: str, count: int) -> list[dict]:
    """Calculate SMA, EMA, MACD, RSI, BOLL using MyTT."""
    import akshare as ak
    import pandas as pd
    import numpy as np
    from MyTT import MA, EMA, MACD, RSI, BOLL

    clean_sym = clean_hk_symbol(symbol)
    try:
        # Fetch larger window to compute moving averages reliably
        df = ak.stock_hk_hist(symbol=clean_sym, period="daily", adjust="qfq")
        if df is None or df.empty:
            return []
        
        col_map = {
            "日期": "time",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume"
        }
        df = df.rename(columns=col_map)
        df = df[list(col_map.values())].tail(count).copy()
        df["time"] = pd.to_datetime(df["time"]).dt.strftime("%Y-%m-%d")

        CLOSE = df["close"].values.astype(float)
        
        # SMA & EMA
        df["ma50"] = MA(CLOSE, 50)
        df["ma200"] = MA(CLOSE, 200)
        df["ema10"] = EMA(CLOSE, 10)
        
        # MACD
        dif, dea, macd_val = MACD(CLOSE)
        df["macd"] = dif
        df["macd_signal"] = dea
        df["macd_hist"] = macd_val
        
        # RSI
        df["rsi"] = RSI(CLOSE)
        
        # BOLL
        up, mid, low_b = BOLL(CLOSE)
        df["boll_ub"] = up
        df["boll_mid"] = mid
        df["boll_lb"] = low_b

        # Round floats
        for col in df.columns:
            if df[col].dtype in [np.float64, np.float32]:
                df[col] = df[col].round(3).replace({np.nan: None})
        
        return df.to_dict(orient="records")
    except Exception as exc:
        print(f"Error calculating indicators: {exc}", file=sys.stderr)
        return []


def fetch_fundamentals(symbol: str) -> dict:
    """Fetch current quotes (Tencent) and multi-year core financial statement summaries (Eastmoney)."""
    import akshare as ak
    import requests
    import pandas as pd

    clean_sym = clean_hk_symbol(symbol)
    output = {
        "symbol": symbol,
        "clean_symbol": clean_sym,
        "name": "HK Stock",
        "market_cap": None,
        "pe_ratio": None,
        "pb_ratio": None,
        "price": None,
        "currency": "HKD",
        "financials": []
    }

    # 1) Get Realtime quote from Tencent Finance
    try:
        url = f"https://qt.gtimg.cn/q=r_hk{clean_sym}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        text = r.text.strip()
        if "=" in text:
            val = text.split("=", 1)[1].strip(' ";')
            parts = val.split("~")
            if len(parts) > 60:
                output["name"] = parts[1]
                output["price"] = float(parts[3]) if parts[3] else None
                output["pe_ratio"] = float(parts[39]) if parts[39] else None
                # parts[44] is market cap in 100M HKD
                output["market_cap"] = int(float(parts[44]) * 10**8) if parts[44] else None
                output["pb_ratio"] = float(parts[57]) if parts[57] else None
                output["currency"] = parts[75] if len(parts) > 75 and parts[75] else "HKD"
    except Exception as exc:
        print(f"Warning: Tencent quote fetch failed: {exc}", file=sys.stderr)

    # 2) Get Multi-year financial statements via Eastmoney Major Indicators
    try:
        df_fin = ak.stock_financial_hk_analysis_indicator_em(symbol=clean_sym)
        if df_fin is not None and not df_fin.empty:
            # We take the last 4 reporting periods (typically annual, or report date periods)
            cols = [
                "REPORT_DATE", "BASIC_EPS", "OPERATE_INCOME", "OPERATE_INCOME_YOY",
                "GROSS_PROFIT_RATIO", "HOLDER_PROFIT", "HOLDER_PROFIT_YOY",
                "ROE_AVG", "DEBT_ASSET_RATIO", "CURRENT_RATIO"
            ]
            valid_cols = [c for c in cols if c in df_fin.columns]
            df_sub = df_fin[valid_cols].head(6).copy()
            
            # Format report dates
            df_sub["REPORT_DATE"] = pd.to_datetime(df_sub["REPORT_DATE"]).dt.strftime("%Y-%m-%d")
            
            # Translate keys for JSON
            rename_map = {
                "REPORT_DATE": "date",
                "BASIC_EPS": "eps",
                "OPERATE_INCOME": "revenue",
                "OPERATE_INCOME_YOY": "revenue_yoy",
                "GROSS_PROFIT_RATIO": "gross_margin",
                "HOLDER_PROFIT": "net_income",
                "HOLDER_PROFIT_YOY": "net_income_yoy",
                "ROE_AVG": "roe",
                "DEBT_ASSET_RATIO": "debt_ratio",
                "CURRENT_RATIO": "current_ratio"
            }
            df_sub = df_sub.rename(columns=rename_map)
            # Replace NaNs
            df_sub = df_sub.replace({pd.NA: None, pd.NaT: None})
            
            # Format large numbers
            for col in ["revenue", "net_income"]:
                if col in df_sub.columns:
                    df_sub[col] = pd.to_numeric(df_sub[col], errors="coerce").fillna(0).astype(int)

            output["financials"] = df_sub.to_dict(orient="records")
    except Exception as exc:
        print(f"Warning: Eastmoney financials fetch failed: {exc}", file=sys.stderr)

    return output


def fetch_news(symbol: str) -> list[dict]:
    """Fetch recent news articles from Eastmoney Stock News."""
    import akshare as ak
    import pandas as pd

    clean_sym = clean_hk_symbol(symbol)
    try:
        df = ak.stock_news_em(symbol=clean_sym)
        if df is None or df.empty:
            return []
        
        rename_map = {
            "新闻标题": "title",
            "新闻内容": "content",
            "发布时间": "pub_date",
            "文章来源": "source",
            "新闻链接": "link"
        }
        df = df.rename(columns=rename_map)
        valid_cols = [c for c in rename_map.values() if c in df.columns]
        df = df[valid_cols].copy()
        
        # Replace NaNs
        df = df.replace({pd.NA: None, pd.NaT: None})
        return df.to_dict(orient="records")
    except Exception as exc:
        print(f"Error fetching HK stock news: {exc}", file=sys.stderr)
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch HK Stock data via AkShare")
    parser.add_argument("--symbol", required=True, help="Stock symbol (e.g. 00700.HK)")
    parser.add_argument("--kline", action="store_true", help="Fetch OHLCV daily history")
    parser.add_argument("--start", default=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"))
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--indicators", action="store_true", help="Calculate SMA, EMA, MACD, RSI, BOLL")
    parser.add_argument("--lookback", type=int, default=120, help="Lookback days for indicators")
    parser.add_argument("--fundamentals", action="store_true", help="Fetch core fundamentals and multiyear records")
    parser.add_argument("--news", action="store_true", help="Fetch company news")
    args = parser.parse_args()

    symbol = args.symbol
    result = {}

    if args.kline:
        result["kline"] = fetch_ohlcv(symbol, args.start, args.end)
    
    if args.indicators:
        result["indicators"] = fetch_indicators(symbol, args.lookback)
        
    if args.fundamentals:
        result["fundamentals"] = fetch_fundamentals(symbol)
        
    if args.news:
        result["news"] = fetch_news(symbol)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
