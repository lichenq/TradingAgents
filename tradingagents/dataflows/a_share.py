"""A-share data vendor — delegates to a-share-data skill via ``run.sh``."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Annotated, Any, Dict, List

from dateutil.relativedelta import relativedelta

from tradingagents.dataflows.a_share_runner import run_script
from tradingagents.dataflows.cn_market_dates import cn_indicator_end_date, cn_ohlcv_end_date
from tradingagents.dataflows.cn_sentiment import fetch_cn_news_block
from tradingagents.market import normalize_a_share_code, is_hk_ticker

# Per-process cache: fundamentals analyst calls get_fundamentals + 3 statements → same fetch.
_fundamentals_cache: Dict[tuple[str, str], str] = {}


def a_share_fundamentals_failed(payload: str) -> bool:
    """True when skill output has no usable financial rows for the LLM."""
    if not payload:
        return True
    if payload.startswith("<a_share") or "Fundamentals unavailable" in payload:
        return True
    if "归母净利润" in payload or "营业总收入" in payload:
        return False
    low = payload.lower()
    if "timeout" in low or "未获取到" in payload:
        return True
    if '"financial_abstract": []' in payload and '"count": 0' in payload:
        return True
    return "unavailable" in low

_INDICATOR_HINTS = {
    "close_50_sma": "50日均线 (MA50)",
    "close_200_sma": "200日均线 (MA200)",
    "close_10_ema": "10日EMA",
    "macd": "MACD",
    "macds": "MACD Signal",
    "macdh": "MACD Histogram",
    "rsi": "RSI",
    "boll": "BOLL 中轨",
    "boll_ub": "BOLL 上轨",
    "boll_lb": "BOLL 下轨",
}

def _fetch_a_share_realtime_quote(code6: str) -> Dict[str, Any] | None:
    ok, raw, data = run_script(
        "fetch_realtime.py",
        ["--quote", code6, "--json"],
        timeout=25,
    )
    if ok and isinstance(data, dict):
        return data
    return None


def _last_bar_date_from_ohlcv(body: str) -> str:
    last = ""
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.lower().startswith("time,"):
            continue
        last = str(line.split(",")[0])[:10]
    return last


def _cn_market_asof_header(
    trade_date: str,
    *,
    code6: str,
    symbol: str,
    ohlcv_end: str,
    last_bar: str,
    quote: Dict[str, Any] | None,
) -> str:
    lines = [
        f"# Analysis trade_date: {trade_date}",
        f"# OHLCV requested through: {ohlcv_end}",
        f"# Last daily bar in CSV: {last_bar or 'unknown'}",
        f"# Data retrieved at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if quote:
        q_date = quote.get("日期") or quote.get("date") or ""
        price = quote.get("最新价") or quote.get("price")
        lines.append(f"# Realtime quote date: {q_date}")
        lines.append(f"# Realtime price (分析时最新价): {price}")
        lines.append(f"# Realtime updated: {quote.get('更新时间', '')}")
        lines.append(f"# Market status: {quote.get('市场状态', '')}")
        note = quote.get("备注")
        if note:
            lines.append(f"# Quote note: {note}")
        lines.append(
            "# Use the realtime price above for 当前价/最新收盘价 when it is newer than the last daily bar."
        )
    elif last_bar and last_bar < ohlcv_end:
        lines.append(
            f"# Note: last daily bar ({last_bar}) is before request end ({ohlcv_end}); "
            "intraday close may differ until the session is recorded in daily history."
        )
    lines.append("")
    return "\n".join(lines)


def _build_hk_ohlcv_block(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    ok, raw, data = run_script(
        "fetch_hk_data.py",
        ["--symbol", symbol, "--kline", "--start", start_date, "--end", end_date],
        timeout=35,
    )
    if not ok or not isinstance(data, dict):
        return raw or f"No data found for HK symbol '{symbol}'"
    
    kline = data.get("kline") or []
    if not kline:
        return f"No daily bars returned for HK symbol '{symbol}'"
        
    lines = [
        f"# HK stock data for {symbol.upper()} from {start_date} to {end_date}",
        f"# Total records: {len(kline)}",
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "time,open,high,low,close,volume,pctChg"
    ]
    for row in kline:
        lines.append(f"{row['time']},{row['open']},{row['high']},{row['low']},{row['close']},{row['volume']},{row.get('pctChg', 0.0)}")
    return "\n".join(lines)


def _build_a_share_ohlcv_block(
    symbol: str,
    start_date: str,
    trade_date: str,
    *,
    use_cache: bool = True,
) -> str:
    code6 = normalize_a_share_code(symbol)
    ohlcv_end = cn_ohlcv_end_date(trade_date)

    if use_cache:
        from tradingagents.dataflows.cn_prefetch import get_prefetched

        cached = get_prefetched(f"kline:{code6}")
        if cached:
            return cached

    ok, raw, rows = run_script(
        "fetch_history.py",
        [
            "--kline", code6,
            "--start", start_date,
            "--end", ohlcv_end,
            "--freq", "1d",
            "--count", "500",
            "--json",
        ],
        timeout=40,
    )
    if not ok:
        return raw
    if not isinstance(rows, list) or not rows:
        return f"No A-share OHLCV for {code6} between {start_date} and {ohlcv_end}"

    lines = ["time,open,high,low,close,volume,pctChg"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"{row.get('time','')},{row.get('open','')},{row.get('high','')},"
            f"{row.get('low','')},{row.get('close','')},{row.get('volume','')},"
            f"{row.get('pctChg','')}"
        )
    csv_body = "\n".join(lines)
    last_bar = _last_bar_date_from_ohlcv(csv_body)
    quote = _fetch_a_share_realtime_quote(code6)
    header = _cn_market_asof_header(
        trade_date,
        code6=code6,
        symbol=symbol,
        ohlcv_end=ohlcv_end,
        last_bar=last_bar,
        quote=quote,
    )
    return (
        header
        + f"# A-share OHLCV for {code6} ({symbol}) from {start_date} to {ohlcv_end}\n"
        + f"# Total records: {len(lines) - 1}\n"
        + "# Data source: a-share-data (Tencent/Sina/Eastmoney)\n\n"
        + csv_body
    )


_TECH_MAP = {
    "close_50_sma": "MA",
    "close_200_sma": "MA",
    "close_10_ema": "MA",
    "macd": "MACD",
    "macds": "MACD",
    "macdh": "MACD",
    "rsi": "RSI",
    "boll": "BOLL",
    "boll_ub": "BOLL",
    "boll_lb": "BOLL",
}


def get_a_share_stock_data(
    symbol: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")
    if is_hk_ticker(symbol):
        return _build_hk_ohlcv_block(symbol, start_date, end_date)
    # ``end_date`` from the LLM may lag; always anchor freshness on ``end_date`` as trade_date.
    return _build_a_share_ohlcv_block(symbol, start_date, end_date, use_cache=True)


def get_a_share_indicators(
    symbol: Annotated[str, "ticker symbol"],
    indicator: Annotated[str, "technical indicator name"],
    curr_date: Annotated[str, "trade date YYYY-mm-dd"],
    look_back_days: Annotated[int, "lookback days"],
) -> str:
    if is_hk_ticker(symbol):
        count = max(look_back_days + 30, 120)
        ok, raw, data = run_script(
            "fetch_hk_data.py",
            ["--symbol", symbol, "--indicators", "--lookback", str(count)],
            timeout=35,
        )
        if not ok or not isinstance(data, dict):
            return raw or f"No indicator data for HK symbol '{symbol}'"
        rows = data.get("indicators") or []
        code6 = symbol.upper()
    else:
        code6 = normalize_a_share_code(symbol)
        tech = _TECH_MAP.get(indicator, "MACD,RSI,BOLL,MA")
        count = max(look_back_days + 30, 120)

        ok, raw, rows = run_script(
            "fetch_technical.py",
            [code6, "--freq", "1d", "--count", str(count), "--indicators", tech, "--json"],
            timeout=40,
        )
        if not ok:
            return raw
        if not isinstance(rows, list) or not rows:
            return f"No indicator data for {code6} on {curr_date}"

    end_date = cn_indicator_end_date(curr_date)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    before = end_dt - relativedelta(days=look_back_days)

    ind_string = ""
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        t = row.get("time") or row.get("date") or row.get("datetime")
        if not t:
            continue
        try:
            row_dt = datetime.strptime(str(t)[:10], "%Y-%m-%d")
        except ValueError:
            continue
        if row_dt < before or row_dt > end_dt:
            continue
        val = _pick_indicator_value(row, indicator)
        ind_string += f"{str(t)[:10]}: {val}\n"

    hint = _INDICATOR_HINTS.get(indicator, indicator)
    return (
        f"## {indicator} ({hint}) for {code6}\n"
        f"## Analysis trade_date: {curr_date} · data through: {end_date}\n"
        f"## Range: {before.strftime('%Y-%m-%d')} to {end_date}\n\n"
        f"{ind_string or 'N/A: no rows in range'}\n"
    )


def _pick_indicator_value(row: Dict[str, Any], indicator: str) -> str:
    keys = list(row.keys())
    lowered = {k.lower(): k for k in keys}
    candidates = {
        "close_50_sma": ["ma50", "ma_50", "sma50", "close_50_sma"],
        "close_200_sma": ["ma200", "ma_200", "sma200", "close_200_sma"],
        "close_10_ema": ["ema10", "close_10_ema"],
        "macd": ["macd", "macd_dif"],
        "macds": ["macds", "macd_signal", "signal"],
        "macdh": ["macdh", "macd_hist", "hist"],
        "rsi": ["rsi", "rsi6", "rsi12"],
        "boll": ["boll", "boll_mid", "middle"],
        "boll_ub": ["boll_ub", "upper", "ub"],
        "boll_lb": ["boll_lb", "lower", "lb"],
    }.get(indicator, [indicator])

    for name in candidates:
        for probe in (name, name.lower(), name.upper()):
            if probe in row:
                return str(row[probe])
            if probe.lower() in lowered:
                return str(row[lowered[probe.lower()]])
    # fallback: last numeric column
    for k, v in row.items():
        if k.lower() in ("time", "date", "code", "open", "high", "low", "close", "volume"):
            continue
        if v is not None:
            return str(v)
    return "N/A"


def get_a_share_news(
    ticker: Annotated[str, "ticker"],
    start_date: Annotated[str, "start yyyy-mm-dd"],
    end_date: Annotated[str, "end yyyy-mm-dd"],
) -> str:
    if is_hk_ticker(ticker):
        ok, raw, data = run_script(
            "fetch_hk_data.py",
            ["--symbol", ticker, "--news"],
            timeout=35,
        )
        if not ok or not isinstance(data, dict):
            return raw or f"No news found for HK symbol '{ticker}'"
        news = data.get("news") or []
        if not news:
            return f"No news articles found for HK symbol '{ticker}'"
            
        lines = [
            f"## {ticker.upper()} 新闻与公告 ({start_date} 至 {end_date})",
            "",
        ]
        for rec in news[:15]:
            title = rec.get("title") or ""
            pub = rec.get("pub_date") or ""
            src = rec.get("source") or ""
            summary = rec.get("content") or ""
            lines.append(f"### {title} ({pub}) [{src}]")
            if summary:
                lines.append(str(summary)[:500])
            lines.append("")
        return "\n".join(lines).strip()

    from tradingagents.dataflows.cn_prefetch import get_prefetched

    code6 = normalize_a_share_code(ticker)
    cached = get_prefetched(f"news_company:{code6}")
    if cached:
        return cached
    return fetch_cn_news_block(ticker, start_date, end_date)


def get_a_share_global_news(
    curr_date: Annotated[str, "current date yyyy-mm-dd"],
    look_back_days: int = 7,
    limit: int = 10,
) -> str:
    """CN macro/industry headlines via a-share-data only (no Yahoo Finance)."""
    from tradingagents.dataflows.a_share_news import (
        filter_market_items_by_queries,
        format_market_items,
    )
    from tradingagents.dataflows.config import get_config
    from tradingagents.dataflows.sector_queries import merge_news_queries

    config = get_config()
    if look_back_days is None:
        look_back_days = config.get("global_news_lookback_days", 7)
    if limit is None:
        limit = config.get("global_news_article_limit", 10)
    look_back_days = int(look_back_days)
    limit = int(limit)

    ticker = config.get("company_of_interest") or ""
    if ticker:
        from tradingagents.dataflows.cn_prefetch import get_prefetched

        code6 = normalize_a_share_code(ticker)
        cached = get_prefetched(f"news_macro:{code6}")
        if cached:
            company = get_prefetched(f"news_company:{code6}") or ""
            if company and "unavailable" not in company.lower():
                return f"{cached}\n\n{company}"
            return cached

    queries = merge_news_queries(config)
    parts: List[str] = []

    ok, raw, data = run_script(
        "fetch_realtime.py",
        ["--market-news", "--news-limit", str(max(limit * 3, 30)), "--json"],
        timeout=25,
    )
    if ok and isinstance(data, dict):
        items = data.get("data") or []
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - relativedelta(days=look_back_days)
        filtered = filter_market_items_by_queries(items, queries, max_items=limit)
        block = format_market_items(
            filtered,
            header=f"## A股快讯 (DangInvest，按宏观/行业关键词过滤) · {start_dt.date()} 至 {curr_date}",
            limit=limit,
        )
        if block:
            parts.append(block)

    ticker = config.get("company_of_interest")
    if ticker:
        start_dt = (
            datetime.strptime(curr_date, "%Y-%m-%d") - relativedelta(days=look_back_days)
        ).strftime("%Y-%m-%d")
        company_news = fetch_cn_news_block(ticker, start_dt, curr_date)
        if company_news and "unavailable" not in company_news.lower():
            parts.append(
                f"## 本股相关新闻（东财）· {normalize_a_share_code(ticker)}\n\n{company_news}"
            )

    if not parts:
        return raw if raw else f"No A-share macro/sector news for {curr_date}"
    return "\n\n".join(parts)


def get_a_share_fundamentals(
    symbol: Annotated[str, "ticker"],
    curr_date: Annotated[str, "reference date"],
) -> str:
    if is_hk_ticker(symbol):
        cache_key = (symbol.upper(), str(curr_date))
        if cache_key in _fundamentals_cache:
            return _fundamentals_cache[cache_key]

        ok, raw, data = run_script(
            "fetch_hk_data.py",
            ["--symbol", symbol, "--fundamentals"],
            timeout=35,
        )
        if not ok or not isinstance(data, dict):
            return raw or f"No fundamentals found for HK symbol '{symbol}'"
        fund = data.get("fundamentals") or {}
        if not fund:
            return f"No fundamentals records found for HK symbol '{symbol}'"
            
        lines = [
            f"## HK Stock Fundamentals: {fund.get('name', 'N/A')} ({symbol.upper()})",
            f"Current Price: {fund.get('price', 'N/A')} {fund.get('currency', 'HKD')}",
            f"Market Cap: {fund.get('market_cap', 'N/A'):,}" if fund.get("market_cap") else "Market Cap: N/A",
            f"PE Ratio (TTM): {fund.get('pe_ratio', 'N/A')}",
            f"PB Ratio: {fund.get('pb_ratio', 'N/A')}",
            "",
            "### Multi-Year Core Financial Indicators",
            "| Reporting Date | EPS (HKD) | Revenue (HKD) | Revenue YoY (%) | Gross Margin % | Net Income (HKD) | Net Income YoY (%) | ROE (%) | Debt/Asset Ratio (%) | Current Ratio |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
        ]
        for row in fund.get("financials", []):
            lines.append(
                f"| {row.get('date', 'N/A')} "
                f"| {row.get('eps', 'N/A')} "
                f"| {row.get('revenue', 0):,} "
                f"| {row.get('revenue_yoy', 'N/A')} "
                f"| {row.get('gross_margin', 'N/A')} "
                f"| {row.get('net_income', 0):,} "
                f"| {row.get('net_income_yoy', 'N/A')} "
                f"| {row.get('roe', 'N/A')} "
                f"| {row.get('debt_ratio', 'N/A')} "
                f"| {row.get('current_ratio', 'N/A')} |"
            )
        result = "\n".join(lines)
        _fundamentals_cache[cache_key] = result
        return result

    code6 = normalize_a_share_code(symbol)
    cache_key = (code6, str(curr_date))
    if cache_key in _fundamentals_cache:
        return _fundamentals_cache[cache_key]

    # Primary: akshare 综合财务指标 (fetch_history_fallback._financials_from_akshare)
    ok, raw, data = run_script(
        "fetch_history.py",
        ["--financials", code6, "--json"],
        timeout=45,
    )
    if ok and data:
        result = (
            f"## A-share fundamentals for {code6}\n\n"
            f"{json.dumps(data, ensure_ascii=False, indent=2)[:8000]}"
        )
        _fundamentals_cache[cache_key] = result
        return result

    # Fallback: 东财财务摘要 + 业绩 (fetch_stock_events); ~40s typical — needs timeout >= 45
    ok2, raw2, events = run_script(
        "fetch_stock_events.py",
        [
            "--code",
            code6,
            "--limit",
            "15",
            "--skip-sentiment",
            "--max-seconds",
            "50",
            "--json",
        ],
        timeout=55,
    )
    if ok2 and isinstance(events, dict):
        perf = events.get("performance") or {}
        result = (
            f"## A-share fundamentals snapshot for {code6} "
            f"(东财/akshare events · performance)\n\n"
            f"{json.dumps(perf, ensure_ascii=False, indent=2)[:6000]}"
        )
        _fundamentals_cache[cache_key] = result
        return result

    result = raw2 or raw or f"Fundamentals unavailable for {code6}"
    _fundamentals_cache[cache_key] = result
    return result


def get_a_share_balance_sheet(
    symbol: Annotated[str, "ticker"],
    freq: Annotated[str, "annual or quarterly"] = "quarterly",
    curr_date: Annotated[str, "reference date YYYY-MM-DD"] = None,
) -> str:
    _ = freq  # a_share financials script does not split by freq yet
    ref = curr_date or datetime.now().strftime("%Y-%m-%d")
    return get_a_share_fundamentals(symbol, ref)


def get_a_share_cashflow(
    symbol: Annotated[str, "ticker"],
    freq: Annotated[str, "annual or quarterly"] = "quarterly",
    curr_date: Annotated[str, "reference date YYYY-MM-DD"] = None,
) -> str:
    _ = freq
    ref = curr_date or datetime.now().strftime("%Y-%m-%d")
    return get_a_share_fundamentals(symbol, ref)


def get_a_share_income_statement(
    symbol: Annotated[str, "ticker"],
    freq: Annotated[str, "annual or quarterly"] = "quarterly",
    curr_date: Annotated[str, "reference date YYYY-MM-DD"] = None,
) -> str:
    _ = freq
    ref = curr_date or datetime.now().strftime("%Y-%m-%d")
    return get_a_share_fundamentals(symbol, ref)


def get_a_share_insider_transactions(
    symbol: Annotated[str, "ticker"],
    curr_date: Annotated[str, "reference date YYYY-MM-DD"] = None,
) -> str:
    """Map to A-share 增减持/回购 disclosures."""
    code6 = normalize_a_share_code(symbol)
    ok, raw, data = run_script(
        "fetch_stock_events.py",
        ["--code", code6, "--limit", "30", "--json"],
        timeout=35,
    )
    if not ok or not isinstance(data, dict):
        return raw
    block = data.get("holder_change_buyback") or {}
    return (
        f"## Holder changes / buybacks for {code6}\n\n"
        f"{json.dumps(block, ensure_ascii=False, indent=2)[:6000]}"
    )
