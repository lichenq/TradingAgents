"""Classify individual tickers into Tuige setup modules (Phase 2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

TUIGE_SETUPS = (
    "trend-setups",
    "limit-up-pullback-setups",
    "relay-setups",
    "washout-breakout-setups",
    "unclassified",
)

STRATEGY_SETUP_HINT: Dict[str, str] = {
    "trend_pullback": "trend-setups",
    "macd_resonance": "trend-setups",
    "macd_second_golden_cross": "washout-breakout-setups",
    "em_hot_momentum": "relay-setups",
    "em_fomo_exit": "relay-setups",
}


@dataclass
class SetupClassification:
    setup: str = "unclassified"
    confidence: float = 0.0
    rationale: str = ""
    pattern_hits: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "setup": self.setup,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "pattern_hits": list(self.pattern_hits),
        }


def _limit_up_threshold(code6: str) -> float:
    if code6.startswith(("688", "300", "301")):
        return 19.0
    if code6.startswith(("8", "4")):
        return 29.0
    return 9.5


def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.sort_values("time").copy()
    if len(out) < 5:
        return out
    prev_close = out["close"].shift(1)
    out["pct_chg"] = (out["close"] - prev_close) / prev_close.replace(0, pd.NA) * 100
    out["pct_chg"] = out["pct_chg"].fillna(0.0)
    if "MA5" not in out.columns:
        out["MA5"] = out["close"].rolling(5).mean()
    if "MA10" not in out.columns:
        out["MA10"] = out["close"].rolling(10).mean()
    if "MA30" not in out.columns:
        out["MA30"] = out["close"].rolling(30).mean()
    out["vol_ma20"] = out["volume"].rolling(20).mean()
    return out


def _is_limit_up(pct: float, threshold: float) -> bool:
    return pct >= threshold - 0.5


def _score_relay(df: pd.DataFrame, threshold: float) -> Tuple[float, List[str]]:
    hits: List[str] = []
    if len(df) < 8:
        return 0.0, hits
    recent = df.iloc[-6:]
    limit_days = sum(1 for _, r in recent.iterrows() if _is_limit_up(float(r["pct_chg"]), threshold))
    if limit_days >= 2:
        hits.append(f"consecutive_limit_up={limit_days}")
        return 0.85 + min(limit_days, 3) * 0.05, hits
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if _is_limit_up(float(prev["pct_chg"]), threshold) and float(last["pct_chg"]) > 3:
        hits.append("limit_up_continuation")
        return 0.75, hits
    return 0.0, hits


def _score_limit_up_pullback(df: pd.DataFrame, threshold: float) -> Tuple[float, List[str]]:
    hits: List[str] = []
    if len(df) < 15:
        return 0.0, hits
    window = df.iloc[-20:]
    limit_idx = None
    for i in range(len(window) - 1, -1, -1):
        if _is_limit_up(float(window.iloc[i]["pct_chg"]), threshold):
            limit_idx = i
            break
    if limit_idx is None or limit_idx >= len(window) - 2:
        return 0.0, hits
    limit_bar = window.iloc[limit_idx]
    after = window.iloc[limit_idx + 1 :]
    if after.empty:
        return 0.0, hits
    limit_low = float(limit_bar["low"])
    limit_close = float(limit_bar["close"])
    last_close = float(after.iloc[-1]["close"])
    if last_close < limit_low * 0.97:
        return 0.0, hits
    if last_close > limit_close * 1.02:
        return 0.0, hits
    pullback_pct = (limit_close - last_close) / limit_close * 100 if limit_close else 0
    if pullback_pct < 1:
        return 0.0, hits
    hits.append(f"limit_up_pullback={pullback_pct:.1f}%")
    vol_shrink = float(after["volume"].mean()) < float(limit_bar["volume"]) * 0.8
    if vol_shrink:
        hits.append("post_limit_vol_shrink")
    score = 0.65 + min(pullback_pct, 8) * 0.02
    if vol_shrink:
        score += 0.05
    return min(score, 0.9), hits


def _score_washout_breakout(df: pd.DataFrame) -> Tuple[float, List[str]]:
    hits: List[str] = []
    if len(df) < 25:
        return 0.0, hits
    last = df.iloc[-1]
    prev_block = df.iloc[-12:-1]
    vol_ma = float(prev_block["volume"].mean()) if len(prev_block) else 0
    last_vol = float(last["volume"])
    last_pct = float(last["pct_chg"])
    if vol_ma > 0 and last_vol > vol_ma * 1.4 and last_pct > 2:
        hits.append("volume_breakout")
        score = 0.6 + min(last_pct, 6) * 0.03
    else:
        score = 0.0
    low10 = float(df.iloc[-11:-1]["low"].min())
    if float(last["low"]) < low10 * 0.995 and float(last["close"]) > low10:
        hits.append("fake_breakdown_recovery")
        score = max(score, 0.7)
    vol_trend = df.iloc[-8:-1]["volume"].values
    if len(vol_trend) >= 5 and vol_trend[-1] < vol_trend[0] * 0.7:
        if last_vol > vol_ma * 1.3 and last_pct > 1.5:
            hits.append("squeeze_then_breakout")
            score = max(score, 0.72)
    return min(score, 0.88), hits


def _score_trend(df: pd.DataFrame) -> Tuple[float, List[str]]:
    hits: List[str] = []
    if len(df) < 35:
        return 0.0, hits
    last = df.iloc[-1]
    ma10, ma30 = float(last["MA10"]), float(last["MA30"])
    close = float(last["close"])
    if pd.isna(ma10) or pd.isna(ma30) or ma30 <= 0:
        return 0.0, hits
    if ma10 <= ma30 or close <= ma30:
        return 0.0, hits
    dist_ma10 = abs(close - ma10) / ma10 * 100
    if dist_ma10 > 4:
        return 0.0, hits
    hits.append(f"ma10_pullback={dist_ma10:.1f}%")
    score = 0.55 + max(0, (ma10 / ma30 - 1) * 5)
    return min(score, 0.85), hits


def classify_setup(
    df: pd.DataFrame,
    *,
    code6: str = "",
    strategy_hint: str = "",
) -> SetupClassification:
    """Map K-line structure to a Tuige setup module."""
    prepared = _prepare_df(df)
    if len(prepared) < 10:
        return SetupClassification(
            setup="unclassified",
            rationale="K线不足，无法分类",
        )

    threshold = _limit_up_threshold(code6)
    threshold = _limit_up_threshold(code6)
    scorers = {
        "relay-setups": lambda d: _score_relay(d, threshold),
        "limit-up-pullback-setups": lambda d: _score_limit_up_pullback(d, threshold),
        "washout-breakout-setups": _score_washout_breakout,
        "trend-setups": _score_trend,
    }

    best_setup = "unclassified"
    best_score = 0.0
    best_hits: List[str] = []

    for setup, fn in scorers.items():
        score, hits = fn(prepared)
        if score > best_score:
            best_score = score
            best_setup = setup
            best_hits = hits

    hint = STRATEGY_SETUP_HINT.get(strategy_hint, "")
    if best_score < 0.55 and hint:
        best_setup = hint
        best_score = 0.5
        best_hits = [f"strategy_hint={strategy_hint}"]

    if best_score < 0.5:
        return SetupClassification(
            setup="unclassified",
            confidence=best_score,
            rationale="未匹配明确 Tuige 场景结构",
            pattern_hits=tuple(best_hits),
        )

    return SetupClassification(
        setup=best_setup,
        confidence=best_score,
        rationale=f"Tuige {best_setup}: {', '.join(best_hits) or 'pattern match'}",
        pattern_hits=tuple(best_hits),
    )


def classify_setup_from_code(code: str, trade_date: str) -> Optional[SetupClassification]:
    """Best-effort setup classification for standalone analyze."""
    code6 = "".join(ch for ch in code if ch.isdigit())[-6:]
    if not code6:
        return None
    try:
        from tradingagents.dataflows.a_share_runner import run_script

        ok, _, data = run_script(
            "fetch_history.py",
            ["--kline-batch", code6, "--count", "120", "--json"],
            timeout=45,
        )
        if not ok or not isinstance(data, dict):
            return None
        results = data.get("results") or []
        if not results or not results[0].get("ok"):
            return None
        hist = results[0].get("data") or []
        if len(hist) < 30:
            return None
        df = pd.DataFrame(hist)
        return classify_setup(df, code6=code6)
    except Exception:
        return None
