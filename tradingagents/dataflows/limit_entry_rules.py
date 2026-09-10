"""Limit-order entry rules: backtest helpers and live entry-level suggestions."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence

from tradingagents.dataflows.a_share_runner import run_script
from tradingagents.dataflows.cn_prefetch import get_prefetched
from tradingagents.market import normalize_a_share_code

logger = logging.getLogger(__name__)

FILL_DAYS_DEFAULT = 10
FILL_DAYS_V2 = 15
MIN_DISCOUNT_PCT = 5.0
MACD_DEEP_DISCOUNT_PCT = 8.0
MACD_DEEP_PCT = 0.92
MACD_PL_MULT = 0.97
FILL_CONFIRM_RATIO = 0.98
ATR_STOP_MULT_V2 = 0.75


@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    pct: float = 0.0
    ma20: Optional[float] = None
    boll_lower: Optional[float] = None
    atr14: Optional[float] = None
    macd_dif: Optional[float] = None
    macd_dea: Optional[float] = None
    rsi: Optional[float] = None


def fetch_history_bars(code6: str, start: str, end: str) -> List[Bar]:
    ok, raw, rows = run_script(
        "fetch_history.py",
        ["--kline", code6, "--start", start, "--end", end, "--freq", "1d", "--count", "500", "--json"],
        timeout=90,
    )
    if not ok or not isinstance(rows, list):
        raise RuntimeError(f"history fetch failed for {code6}: {(raw or '')[:120]}")
    bars: List[Bar] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            bars.append(
                Bar(
                    date=str(row.get("time", ""))[:10],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    pct=float(row.get("pctChg") or 0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    bars.sort(key=lambda b: b.date)
    if len(bars) < 30:
        raise RuntimeError(f"insufficient bars for {code6}: {len(bars)}")
    _enrich_indicators(bars)
    return bars


def _ema_series(values: Sequence[float], span: int) -> List[float]:
    if not values:
        return []
    alpha = 2 / (span + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def _enrich_indicators(bars: List[Bar]) -> None:
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    difs = [a - b for a, b in zip(ema12, ema26)]
    deas = _ema_series(difs, 9)

    for i, b in enumerate(bars):
        if i >= 19:
            sl = closes[i - 19 : i + 1]
            m = sum(sl) / 20
            std = math.sqrt(sum((x - m) ** 2 for x in sl) / 20)
            b.boll_lower = m - 2 * std
            b.ma20 = m
        b.macd_dif = difs[i]
        b.macd_dea = deas[i]
        b.rsi = _rsi(closes, i)
        b.atr14 = _atr(highs, lows, closes, i)


def _rsi(closes: Sequence[float], i: int, period: int = 14) -> Optional[float]:
    if i < period:
        return None
    gains, losses = [], []
    for j in range(i - period + 1, i + 1):
        ch = closes[j] - closes[j - 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], i: int, n: int = 14) -> Optional[float]:
    if i < n:
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        tr = max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]), abs(lows[j] - closes[j - 1]))
        trs.append(tr)
    return sum(trs) / n


def prior_low(bars: List[Bar], i: int, lookback: int = 20) -> Optional[float]:
    if i < 1:
        return None
    start = max(0, i - lookback)
    return min(b.low for b in bars[start:i])


def is_macd_dead_cross(bars: List[Bar], i: int) -> bool:
    if i < 1:
        return False
    p, c = bars[i - 1], bars[i]
    if None in (p.macd_dif, p.macd_dea, c.macd_dif, c.macd_dea):
        return False
    return p.macd_dif >= p.macd_dea and c.macd_dif < c.macd_dea


def signal_macd_bear(bars: List[Bar], i: int) -> bool:
    b = bars[i]
    if b.rsi is None or b.macd_dif is None:
        return False
    return (is_macd_dead_cross(bars, i) or (b.macd_dif < (b.macd_dea or 0))) and b.rsi < 50


def signal_sharp_drop(bars: List[Bar], i: int) -> bool:
    b = bars[i]
    return b.ma20 is not None and b.close < b.ma20 and b.pct <= -3.0


def signal_hybrid_entry(bars: List[Bar], i: int) -> bool:
    """sharp_drop OR (macd_bear AND RSI<45)."""
    b = bars[i]
    if signal_sharp_drop(bars, i):
        return True
    if b.rsi is None:
        return False
    return signal_macd_bear(bars, i) and b.rsi < 45


def _round_price(p: float) -> float:
    return round(p * 2) / 2  # 0.5 yuan tick for most A-shares


def limit_price(rule: str, bars: List[Bar], i: int) -> Optional[float]:
    b = bars[i]
    pl = prior_low(bars, i)
    close = b.close
    candidates: List[float] = []

    if rule == "prior_low_99" and pl:
        candidates = [pl * 0.99]
    elif rule == "prior_low" and pl:
        candidates = [pl]
    elif rule == "boll_lower" and b.boll_lower:
        candidates = [b.boll_lower]
    elif rule == "pct_5":
        candidates = [close * 0.95]
    elif rule == "pct_8":
        candidates = [close * 0.92]
    elif rule == "round_60":
        candidates = [60.0]
    elif rule == "hybrid":
        bear = signal_macd_bear(bars, i)
        opts = []
        if pl:
            opts.append(pl * 0.99)
        if b.boll_lower:
            opts.append(b.boll_lower)
        opts.append(close * (0.95 if bear else 0.97))
        floor = close * (1 - MIN_DISCOUNT_PCT / 100)
        candidates = [x for x in opts if x < floor]
        if not candidates and opts:
            candidates = [min(opts)]
    elif rule == "hybrid_v2_shallow":
        opts = [close * 0.97]
        if b.boll_lower and b.boll_lower < close:
            opts.append(b.boll_lower)
        candidates = [x for x in opts if x > 0 and x < close]
    elif rule == "hybrid_v2_deep":
        opts = []
        if pl:
            opts.append(pl * 0.99)
        opts.append(close * 0.95)
        floor = close * (1 - MIN_DISCOUNT_PCT / 100)
        candidates = [x for x in opts if x < floor]
        if not candidates and opts:
            candidates = [min(opts)]
    else:
        return None

    valid = [c for c in candidates if c > 0 and c < close]
    if not valid:
        return None
    return _round_price(min(valid))


def suggested_stop(bars: List[Bar], i: int, entry: float, *, v2: bool = False) -> float:
    pl = prior_low(bars, i)
    atr = bars[i].atr14 or entry * 0.03
    mult = ATR_STOP_MULT_V2 if v2 else 0.5
    floor_mult = 0.90 if v2 else 0.92
    structural = (pl - mult * atr) if pl else entry * floor_mult
    return _round_price(min(structural, entry * floor_mult))


def _fill_on_bar(bar: Bar, limit: float, *, require_confirm: bool) -> bool:
    if bar.low > limit:
        return False
    if require_confirm:
        return bar.close >= limit * FILL_CONFIRM_RATIO
    return True


@dataclass
class RuleStats:
    rule: str
    signals: int = 0
    filled: int = 0
    fill_days: List[int] = None
    ret_5: List[float] = None
    ret_10: List[float] = None
    ret_20: List[float] = None
    stop_hits: int = 0
    wins_20: int = 0

    def __post_init__(self):
        self.fill_days = self.fill_days or []
        self.ret_5 = self.ret_5 or []
        self.ret_10 = self.ret_10 or []
        self.ret_20 = self.ret_20 or []


def backtest_rule(
    bars: List[Bar],
    rule: str,
    signal_fn: Callable[[List[Bar], int], bool],
    *,
    fill_days: int = FILL_DAYS_DEFAULT,
    require_confirm: bool = False,
    stop_v2: bool = False,
) -> RuleStats:
    st = RuleStats(rule=rule)
    for i in range(30, len(bars) - 21):
        if not signal_fn(bars, i):
            continue
        limit = limit_price(rule, bars, i)
        if limit is None:
            continue
        st.signals += 1
        stop = suggested_stop(bars, i, limit, v2=stop_v2)
        fill_idx = None
        for j in range(i + 1, min(i + 1 + fill_days, len(bars))):
            if _fill_on_bar(bars[j], limit, require_confirm=require_confirm):
                fill_idx = j
                st.fill_days.append(j - i)
                break
        if fill_idx is None:
            continue
        st.filled += 1
        entry = limit
        for h, attr in ((5, "ret_5"), (10, "ret_10"), (20, "ret_20")):
            j = fill_idx + h
            if j < len(bars):
                ret = (bars[j].close - entry) / entry * 100
                getattr(st, attr).append(ret)
                if h == 20 and ret > 0:
                    st.wins_20 += 1
        for j in range(fill_idx, min(fill_idx + 20, len(bars))):
            if bars[j].low <= stop:
                st.stop_hits += 1
                break
    return st


def backtest_tiered(
    bars: List[Bar],
    signal_fn: Callable[[List[Bar], int], bool],
    *,
    fill_days: int = FILL_DAYS_V2,
    require_confirm: bool = False,
    stop_v2: bool = True,
    adaptive: bool = False,
) -> RuleStats:
    """Shallow first, then deep — first fill wins. adaptive: shallow only on sharp_drop."""
    suffix = "_confirm" if require_confirm else ""
    suffix += "_adaptive" if adaptive else ""
    name = f"hybrid_v2_tiered{suffix}"
    st = RuleStats(rule=name)
    for i in range(30, len(bars) - 21):
        if not signal_fn(bars, i):
            continue
        sharp = signal_sharp_drop(bars, i)
        shallow = limit_price("hybrid_v2_shallow", bars, i) if (not adaptive or sharp) else None
        deep = limit_price("hybrid_v2_deep", bars, i)
        if shallow is None and deep is None:
            continue
        st.signals += 1
        fill_idx = None
        entry = None
        for j in range(i + 1, min(i + 1 + fill_days, len(bars))):
            if shallow and _fill_on_bar(bars[j], shallow, require_confirm=require_confirm):
                fill_idx, entry = j, shallow
                break
            if deep and deep != shallow and _fill_on_bar(bars[j], deep, require_confirm=require_confirm):
                fill_idx, entry = j, deep
                break
        if fill_idx is None or entry is None:
            continue
        st.fill_days.append(fill_idx - i)
        st.filled += 1
        stop = suggested_stop(bars, i, entry, v2=stop_v2)
        for h, attr in ((5, "ret_5"), (10, "ret_10"), (20, "ret_20")):
            j = fill_idx + h
            if j < len(bars):
                ret = (bars[j].close - entry) / entry * 100
                getattr(st, attr).append(ret)
                if h == 20 and ret > 0:
                    st.wins_20 += 1
        for j in range(fill_idx, min(fill_idx + 20, len(bars))):
            if bars[j].low <= stop:
                st.stop_hits += 1
                break
    return st


def summarize_stats(st: RuleStats) -> Dict[str, Any]:
    sig = st.signals or 1
    filled = st.filled or 0

    def avg(xs: List[float]) -> Optional[float]:
        return round(sum(xs) / len(xs), 2) if xs else None

    return {
        "rule": st.rule,
        "signals": st.signals,
        "filled": st.filled,
        "fill_rate_pct": round(st.filled / sig * 100, 1),
        "win_rate_20d_pct": round(st.wins_20 / filled * 100, 1) if filled else None,
        "avg_fill_days": round(sum(st.fill_days) / len(st.fill_days), 1) if st.fill_days else None,
        "ret_5d_pct": avg(st.ret_5),
        "ret_10d_pct": avg(st.ret_10),
        "ret_20d_pct": avg(st.ret_20),
        "stop_hit_pct": round(st.stop_hits / filled * 100, 1) if filled else None,
    }


RULE_IDS = (
    "prior_low_99", "prior_low", "boll_lower", "pct_5", "pct_8", "round_60",
    "hybrid", "hybrid_v2_shallow", "hybrid_v2_deep",
)
SIGNAL_MODES = ("macd_bear", "sharp_drop", "hybrid_entry")
COMPARE_RULES = (
    ("hybrid", {"fill_days": 10, "require_confirm": False, "stop_v2": False}),
    ("hybrid_v2_deep", {"fill_days": FILL_DAYS_V2, "require_confirm": False, "stop_v2": True}),
    ("hybrid_v2_tiered", {"tiered": True, "require_confirm": False, "adaptive": False}),
    ("hybrid_v2_tiered_adaptive", {"tiered": True, "require_confirm": False, "adaptive": True}),
    ("hybrid_v2_tiered_adaptive_confirm", {"tiered": True, "require_confirm": True, "adaptive": True}),
    ("hybrid_v2_tiered_confirm", {"tiered": True, "require_confirm": True, "adaptive": False}),
)


def run_compare_for_ticker(ticker: str, start: str, end: str) -> List[Dict[str, Any]]:
    code6 = normalize_a_share_code(ticker)
    bars = fetch_history_bars(code6, start, end)
    signal_fn = signal_hybrid_entry
    rows: List[Dict[str, Any]] = []
    for rule, opts in COMPARE_RULES:
        if opts.get("tiered"):
            st = backtest_tiered(
                bars,
                signal_fn,
                fill_days=FILL_DAYS_V2,
                require_confirm=opts["require_confirm"],
                adaptive=opts.get("adaptive", False),
            )
        else:
            st = backtest_rule(
                bars,
                rule,
                signal_fn,
                fill_days=opts["fill_days"],
                require_confirm=opts["require_confirm"],
                stop_v2=opts["stop_v2"],
            )
        row = summarize_stats(st)
        row["ticker"] = code6
        rows.append(row)
    return rows


def aggregate_compare(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_rule: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_rule.setdefault(r["rule"], []).append(r)

    out = []
    for rule, items in by_rule.items():
        n = len(items)
        out.append({
            "rule": rule,
            "tickers": n,
            "avg_fill_rate_pct": round(sum(x["fill_rate_pct"] for x in items) / n, 1),
            "avg_win_rate_20d_pct": round(
                sum(x["win_rate_20d_pct"] or 0 for x in items) / n, 1
            ),
            "avg_ret_20d_pct": round(
                sum(x["ret_20d_pct"] or 0 for x in items) / n, 2
            ),
            "avg_stop_hit_pct": round(
                sum(x["stop_hit_pct"] or 0 for x in items) / n, 1
            ),
            "total_filled": sum(x["filled"] for x in items),
        })
    out.sort(key=lambda x: (-x["avg_ret_20d_pct"], -x["avg_fill_rate_pct"]))
    for v in out:
        v["score"] = round(
            v["avg_fill_rate_pct"] * 0.35
            + (v["avg_win_rate_20d_pct"] or 0) * 0.35
            + v["avg_ret_20d_pct"] * 10 * 0.30,
            1,
        )
    out.sort(key=lambda x: -x["score"])
    return {"variants": out}


def run_backtest_for_ticker(
    ticker: str,
    start: str,
    end: str,
    *,
    signal_mode: str = "macd_bear",
) -> List[Dict[str, Any]]:
    code6 = normalize_a_share_code(ticker)
    bars = fetch_history_bars(code6, start, end)
    signal_fn = signal_macd_bear if signal_mode == "macd_bear" else signal_sharp_drop
    if signal_mode == "hybrid_entry":
        signal_fn = signal_hybrid_entry
    return [
        summarize_stats(backtest_rule(bars, rule, signal_fn))
        for rule in RULE_IDS
    ]


def _parse_kline_csv(text: str) -> List[Bar]:
    bars: List[Bar] = []
    for line in text.splitlines():
        if not line or line.startswith("#") or line.startswith("time,"):
            continue
        parts = line.split(",")
        if len(parts) < 7:
            continue
        try:
            bars.append(
                Bar(
                    date=parts[0][:10],
                    open=float(parts[1]),
                    high=float(parts[2]),
                    low=float(parts[3]),
                    close=float(parts[4]),
                    pct=float(parts[6] or 0),
                )
            )
        except (ValueError, IndexError):
            continue
    bars.sort(key=lambda b: b.date)
    if len(bars) >= 30:
        _enrich_indicators(bars)
    return bars


def _deep_limit_price(
    bars: List[Bar],
    i: int,
    *,
    min_discount: float,
    deep_pct: float,
    pl_mult: float,
) -> Optional[float]:
    b = bars[i]
    pl = prior_low(bars, i)
    close = b.close
    deep_opts: List[float] = []
    if pl:
        deep_opts.append(pl * pl_mult)
    deep_opts.append(close * deep_pct)
    floor = close * (1 - min_discount / 100)
    candidates = [x for x in deep_opts if x < floor]
    if not candidates and deep_opts:
        candidates = [min(deep_opts)]
    valid = [c for c in candidates if c > 0 and c < close]
    if not valid:
        return None
    return _round_price(min(valid))


def _aggressive_tier_prices(bars: List[Bar], i: int, price: float) -> Dict[str, Any]:
    """现行 hybrid_v2_confirm_adaptive 定价。"""
    sharp = signal_sharp_drop(bars, i)
    pl = prior_low(bars, i)
    deep = limit_price("hybrid_v2_deep", bars, i)
    shallow = limit_price("hybrid_v2_shallow", bars, i) if sharp else None
    first = shallow if shallow else deep
    second = deep if sharp and deep and deep < (first or price) else None
    if second is None and first and pl:
        alt = _round_price(min(first * 0.97, pl * 0.97))
        if alt < first:
            second = alt
    stop = suggested_stop(bars, i, first or price, v2=True) if first else None
    return {
        "hang": signal_hybrid_entry(bars, i) and first is not None,
        "first": first,
        "second": second,
        "stop": stop,
        "first_tag": "首笔(浅)" if sharp else "首笔(深)",
    }


def _conservative_tier_prices(bars: List[Bar], i: int, price: float) -> Dict[str, Any]:
    """P0 仅急跌日建议挂单；非急跌 MACD 路径用 P1 更深折扣作观察价。"""
    sharp = signal_sharp_drop(bars, i)
    pl = prior_low(bars, i)
    macd_only = (
        not sharp
        and signal_macd_bear(bars, i)
        and bars[i].rsi is not None
        and bars[i].rsi < 45
    )

    if sharp:
        tier = _aggressive_tier_prices(bars, i, price)
        return {**tier, "hang": tier["first"] is not None, "mode": "sharp_drop"}

    if macd_only:
        first = _deep_limit_price(
            bars,
            i,
            min_discount=MACD_DEEP_DISCOUNT_PCT,
            deep_pct=MACD_DEEP_PCT,
            pl_mult=MACD_PL_MULT,
        )
        second = None
        if first and pl:
            alt = _round_price(min(first * 0.97, pl * MACD_PL_MULT))
            if alt < first:
                second = alt
        stop = suggested_stop(bars, i, first or price, v2=True) if first else None
        return {
            "hang": False,
            "first": first,
            "second": second,
            "stop": stop,
            "first_tag": "观察深档",
            "mode": "macd_only",
        }

    return {
        "hang": False,
        "first": None,
        "second": None,
        "stop": None,
        "first_tag": "",
        "mode": "none",
    }


def _format_tier_lines(tier: Dict[str, Any], price: float, *, label: str) -> List[str]:
    lines = [f"#### {label}"]
    if not tier.get("hang"):
        lines.append("- **挂单建议**: 否")
        mode = tier.get("mode")
        if mode == "macd_only":
            lines.append(
                "- **原因**: 非急跌日 MACD 偏空（回测 20 日胜率约 39%，低于急跌路径）"
            )
            lines.append(
                "- **等待**: ①单日急跌≥3% 且低于 MA20 ②或 RSI>50 + 放量收复 BOLL 下轨"
            )
            if tier.get("first"):
                lines.append(
                    f"- **下行观察价**（非挂单指令，仅供对照）: "
                    f"{tier['first']:.2f}元"
                    + (f" / 第二档 {tier['second']:.2f}元" if tier.get("second") else "")
                )
                if tier.get("stop"):
                    lines.append(f"- **观察止损参考**: {tier['stop']:.2f}元")
        elif mode == "none":
            lines.append("- **原因**: 未触发入场信号")
        return lines

    lines.append("- **挂单建议**: 是")
    first = tier["first"]
    disc = (price - first) / price * 100 if first else 0
    tag = tier.get("first_tag") or "首笔"
    lines.append(f"- **{tag}**: {first:.2f}元（较现价 -{disc:.1f}%）")
    if tier.get("second"):
        lines.append(f"- **第二笔(深)**: {tier['second']:.2f}元")
    if tier.get("stop"):
        lines.append(f"- **建议止损**: {tier['stop']:.2f}元")
    confirm = round(first * FILL_CONFIRM_RATIO, 2) if first else None
    if confirm:
        lines.append(f"- **成交确认**: 日内触及且收盘≥{confirm:.2f}元（限价×98%）")
    return lines


def _latest_price_from_valuation(code6: str) -> Optional[float]:
    raw = get_prefetched(f"valuation_json:{code6}")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        primary = payload.get("primary") or {}
        return float(primary.get("price"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def signal_macd_only(bars: List[Bar], i: int) -> bool:
    b = bars[i]
    return (
        signal_hybrid_entry(bars, i)
        and not signal_sharp_drop(bars, i)
        and signal_macd_bear(bars, i)
        and b.rsi is not None
        and b.rsi < 45
    )


def signal_sharp_entry(bars: List[Bar], i: int) -> bool:
    return signal_hybrid_entry(bars, i) and signal_sharp_drop(bars, i)


def _stats_from_backtest(st: RuleStats) -> Dict[str, Any]:
    summary = summarize_stats(st)
    return {
        "signals": summary["signals"],
        "filled": summary["filled"],
        "fill_rate_pct": summary["fill_rate_pct"],
        "win_rate_20d_pct": summary["win_rate_20d_pct"],
    }


def backtest_track_stats(bars: List[Bar], signal_fn: Callable[[List[Bar], int], bool]) -> Dict[str, Any]:
    st = backtest_tiered(
        bars,
        signal_fn,
        fill_days=FILL_DAYS_V2,
        require_confirm=True,
        adaptive=True,
    )
    return _stats_from_backtest(st)


def compute_ticker_entry_stats(
    ticker: str,
    trade_date: str,
    *,
    lookback_days: int = 730,
) -> Dict[str, Any]:
    """Per-ticker fill/win stats for current dual-track pricing (no algorithm change)."""
    code6 = normalize_a_share_code(ticker)
    start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    bars = fetch_history_bars(code6, start, trade_date)
    if len(bars) < 51:
        raise RuntimeError(f"insufficient history for entry stats: {code6}")

    i = len(bars) - 1
    bucket = "none"
    if signal_sharp_entry(bars, i):
        bucket = "sharp"
    elif signal_macd_only(bars, i):
        bucket = "macd_only"
    elif signal_hybrid_entry(bars, i):
        bucket = "other"

    bucket_fns = {
        "sharp": signal_sharp_entry,
        "macd_only": signal_macd_only,
        "other": lambda b, j: signal_hybrid_entry(b, j) and not signal_sharp_entry(b, j) and not signal_macd_only(b, j),
    }
    by_bucket = {
        name: backtest_track_stats(bars, fn)
        for name, fn in bucket_fns.items()
    }
    return {
        "ticker": code6,
        "trade_date": trade_date,
        "window": f"{start} → {trade_date}",
        "aggressive": backtest_track_stats(bars, signal_hybrid_entry),
        "conservative": backtest_track_stats(bars, signal_sharp_entry),
        "current_bucket": bucket,
        "current_bucket_stats": by_bucket.get(bucket) if bucket in by_bucket else None,
        "by_bucket": by_bucket,
    }


def _format_pct(val: Optional[float]) -> str:
    return f"{val:.1f}%" if val is not None else "N/A"


def _format_stats_line(label: str, st: Optional[Dict[str, Any]]) -> str:
    if not st or not st.get("signals"):
        return f"- **{label}**: 样本不足"
    fill = _format_pct(st.get("fill_rate_pct"))
    win = _format_pct(st.get("win_rate_20d_pct"))
    return (
        f"- **{label}**: 信号 {st['signals']} · 成交 {st['filled']} · "
        f"成交率 {fill} · 20日胜率 {win}"
    )


def _format_decision_hint(stats: Dict[str, Any], sig_label: str) -> str:
    agg = stats.get("aggressive") or {}
    con = stats.get("conservative") or {}
    cur = stats.get("current_bucket_stats") or {}
    bucket = stats.get("current_bucket", "none")
    lines = ["> **决策参考（成交率 / 胜率优先）**:"]

    if bucket == "macd_only" and cur.get("signals"):
        sharp_st = (stats.get("by_bucket") or {}).get("sharp") or {}
        cur_win = cur.get("win_rate_20d_pct")
        sharp_win = sharp_st.get("win_rate_20d_pct")
        if cur_win is not None and sharp_win is not None and cur_win < sharp_win - 5:
            lines.append(
                f"> 当前为 **{sig_label}**，本票该类型历史胜率 {_format_pct(cur_win)}，"
                f"低于急跌日 {_format_pct(sharp_win)}。"
                f"优先胜率 → 保守轨不挂；优先成交率 → 激进轨可轻仓。"
            )
        else:
            lines.append(
                f"> 当前为 **{sig_label}**，本票该类型历史成交率 {_format_pct(cur.get('fill_rate_pct'))}、"
                f"胜率 {_format_pct(cur_win)}。"
            )
    elif bucket == "sharp" and cur.get("signals"):
        lines.append(
            f"> 当前为 **急跌信号**，本票急跌分档历史成交率 {_format_pct(cur.get('fill_rate_pct'))}、"
            f"胜率 {_format_pct(cur.get('win_rate_20d_pct'))}；双轨均可考虑。"
        )
    elif bucket == "none":
        lines.append("> 当前未触发入场信号；下列胜率为历史同类场景参考。")
    else:
        lines.append(
            f"> 激进轨历史成交率 {_format_pct(agg.get('fill_rate_pct'))} / 胜率 {_format_pct(agg.get('win_rate_20d_pct'))}；"
            f"保守轨 {_format_pct(con.get('fill_rate_pct'))} / {_format_pct(con.get('win_rate_20d_pct'))}。"
        )
    return "\n".join(lines)


def suggest_entry_levels(ticker: str, trade_date: str) -> str:
    """Build dual-track markdown block for verified_market_facts (requires prefetch)."""
    code6 = normalize_a_share_code(ticker)
    kline = get_prefetched(f"kline:{code6}") or ""
    bars = _parse_kline_csv(kline)
    if len(bars) < 30:
        from datetime import datetime, timedelta

        from tradingagents.dataflows.a_share import _build_a_share_ohlcv_block

        start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=120)).strftime(
            "%Y-%m-%d"
        )
        kline = _build_a_share_ohlcv_block(ticker, start, trade_date, use_cache=False)
        bars = _parse_kline_csv(kline)
    if len(bars) < 30:
        raise RuntimeError(f"kline prefetch insufficient for entry levels: {code6}")

    i = len(bars) - 1
    b = bars[i]
    price = _latest_price_from_valuation(code6) or b.close
    pl = prior_low(bars, i)
    sharp = signal_sharp_drop(bars, i)
    entry_sig = signal_hybrid_entry(bars, i)
    aggressive = _aggressive_tier_prices(bars, i, price)
    conservative = _conservative_tier_prices(bars, i, price)

    sig_label = "急跌" if sharp else ("MACD偏空" if signal_macd_bear(bars, i) else "中性")
    stats_block: List[str] = []
    try:
        tstats = compute_ticker_entry_stats(code6, trade_date)
        stats_block = [
            "",
            f"#### 本票历史回测（现行算法 · {tstats['window']}）",
            _format_stats_line("激进轨", tstats.get("aggressive")),
            _format_stats_line("保守轨（仅急跌）", tstats.get("conservative")),
        ]
        if tstats.get("current_bucket") in ("sharp", "macd_only"):
            bl = "急跌分档" if tstats["current_bucket"] == "sharp" else "MACD偏空分档"
            stats_block.append(_format_stats_line(f"当前·{bl}", tstats.get("current_bucket_stats")))
        stats_block.append(_format_decision_hint(tstats, sig_label))
    except Exception as exc:
        logger.warning("ticker entry stats skipped for %s: %s", code6, exc)
        stats_block = [
            "",
            "#### 本票历史回测",
            "- 暂无法计算（行情历史不足或拉取失败）",
            "- 池级参考(6票·2024-2026): 激进轨 成交率~48% 胜率~58% | 保守轨 成交率~34% 胜率~63%",
        ]

    lines = [
        f"### 结构化挂单参考（{code6} · {trade_date} · 双轨）",
        f"- 现价: {price:.2f}元",
        f"- 近20日前低: {pl:.2f}元" if pl else "- 近20日前低: N/A",
        f"- BOLL下轨: {b.boll_lower:.2f}元" if b.boll_lower else "- BOLL下轨: N/A",
        f"- MACD: DIF={b.macd_dif:.3f} DEA={b.macd_dea:.3f}" if b.macd_dif is not None else "- MACD: N/A",
        f"- RSI: {b.rsi:.1f}" if b.rsi is not None else "- RSI: N/A",
        f"- 入场信号: {'触发' if entry_sig else '未触发'}（{sig_label}）",
        "- **双轨说明**: 激进轨=现行算法；保守轨=非急跌不挂 + 深档观察",
        *stats_block,
        "",
    ]
    lines.extend(_format_tier_lines(aggressive, price, label="激进轨（现行 · 机会优先）"))
    lines.append("")
    lines.extend(_format_tier_lines(conservative, price, label="保守轨（P0+P1 · 质量优先）"))
    lines.extend([
        "",
        "- **有效窗**: 15 交易日；浅档仅急跌日",
        "- **右侧加仓触发**: RSI>50 且 MACD柱缩短/金叉",
        "- PM/Trader: 须标明采用哪一轨；Buy/Overweight 引用对应轨价位或说明偏离理由",
    ])
    return "\n".join(lines)


def enrich_verified_with_entry_levels(verified_md: str, ticker: str, trade_date: str) -> str:
    block = suggest_entry_levels(ticker, trade_date)
    base = (verified_md or "").rstrip()
    return f"{base}\n\n{block}\n" if base else f"{block}\n"
