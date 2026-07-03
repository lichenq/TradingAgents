"""Prefetch verified A-share technical indicators before market analysis."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from tradingagents.dataflows.a_share_runner import run_script
from tradingagents.dataflows.cn_prefetch import _cache, get_prefetched
from tradingagents.market import normalize_a_share_code

logger = logging.getLogger(__name__)

_DEFAULT_INDICATORS = "MA,MACD,RSI,BOLL"
_TAIL_ROWS = 5
_VALUE_KEYS = (
    "close",
    "MA5",
    "MA10",
    "MA20",
    "MA60",
    "MACD_DIF",
    "MACD_DEA",
    "MACD",
    "RSI",
    "BOLL_UP",
    "BOLL_MID",
    "BOLL_LOW",
)


def _num(row: Dict[str, Any], key: str) -> Optional[float]:
    val = row.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _row_date(row: Dict[str, Any]) -> str:
    raw = row.get("time") or row.get("date") or row.get("datetime") or ""
    return str(raw)[:10]


def _interpret_signals(rows: List[Dict[str, Any]]) -> List[str]:
    if len(rows) < 2:
        return []
    last, prev = rows[-1], rows[-2]
    signals: List[str] = []

    ma5, ma10, ma20 = _num(last, "MA5"), _num(last, "MA10"), _num(last, "MA20")
    if ma5 is not None and ma10 is not None and ma20 is not None:
        if ma5 > ma10 > ma20:
            signals.append("均线多头排列（MA5>MA10>MA20）")
        elif ma5 < ma10 < ma20:
            signals.append("均线空头排列（MA5<MA10<MA20）")

    dif_n, dea_n = _num(last, "MACD_DIF"), _num(last, "MACD_DEA")
    dif_p, dea_p = _num(prev, "MACD_DIF"), _num(prev, "MACD_DEA")
    if None not in (dif_n, dea_n, dif_p, dea_p):
        if dif_p < dea_p and dif_n > dea_n:
            signals.append("MACD 金叉")
        elif dif_p > dea_p and dif_n < dea_n:
            signals.append("MACD 死叉")
        if dif_n > 0 and dea_n > 0:
            signals.append("MACD 零轴上方")
        elif dif_n < 0 and dea_n < 0:
            signals.append("MACD 零轴下方")

    rsi = _num(last, "RSI")
    if rsi is not None:
        signals.append(f"RSI={rsi:.1f}")

    return signals


def format_cn_technical_block(
    code6: str,
    trade_date: str,
    rows: List[Dict[str, Any]],
) -> str:
    if not rows:
        raise ValueError("technical rows empty")

    tail = rows[-_TAIL_ROWS:]
    last = rows[-1]
    lines = [
        f"## A股技术指标（{code6} · 截至 {trade_date}）",
        f"数据源: fetch_technical.py · 指标: {_DEFAULT_INDICATORS}",
        "",
        "### 最新一根",
    ]
    for key in _VALUE_KEYS:
        val = _num(last, key)
        if val is not None:
            lines.append(f"- {key}: {val:.3f}")

    lines.extend(["", f"### 近{_TAIL_ROWS}日"])
    lines.append("| 日期 | " + " | ".join(_VALUE_KEYS) + " |")
    lines.append("|------|" + "|".join(["------"] * len(_VALUE_KEYS)) + "|")
    for row in tail:
        cells = [_row_date(row)]
        for key in _VALUE_KEYS:
            val = _num(row, key)
            cells.append(f"{val:.3f}" if val is not None else "N/A")
        lines.append("| " + " | ".join(cells) + " |")

    signals = _interpret_signals(rows)
    lines.extend(["", "### 规则化信号"])
    if signals:
        lines.extend(f"- {s}" for s in signals)
    else:
        lines.append("- （数据不足，无法解读交叉/排列）")
    return "\n".join(lines)


def fetch_and_cache_cn_technical(ticker: str, trade_date: str) -> Tuple[str, bool]:
    code6 = normalize_a_share_code(ticker)
    ok, raw, rows = run_script(
        "fetch_technical.py",
        [
            code6,
            "--freq",
            "1d",
            "--count",
            "120",
            "--indicators",
            _DEFAULT_INDICATORS,
            "--json",
        ],
        timeout=45,
    )
    if not ok or not isinstance(rows, list) or not rows:
        msg = (raw or "no rows")[:120]
        _cache(f"technical:{code6}", "")
        return f"FAILED · {msg}", False

    try:
        block = format_cn_technical_block(code6, str(trade_date), rows)
    except ValueError as exc:
        _cache(f"technical:{code6}", "")
        return f"FAILED · {exc}", False

    _cache(f"technical:{code6}", block)
    last = rows[-1]
    dif = _num(last, "MACD_DIF")
    rsi = _num(last, "RSI")
    parts = ["ok"]
    if dif is not None:
        parts.append(f"MACD_DIF {dif:.2f}")
    if rsi is not None:
        parts.append(f"RSI {rsi:.1f}")
    return " · ".join(parts), True


def require_cn_technical_ready(ticker: str) -> str:
    code6 = normalize_a_share_code(ticker)
    block = get_prefetched(f"technical:{code6}") or ""
    if not block.strip():
        raise RuntimeError(
            f"A-share technical prefetch failed for {code6}: "
            "market analysis cannot start without verified MA/MACD/RSI/BOLL. "
            "Check a-share-data skill / network."
        )
    return block
