"""Tuige five-tier market regime detection."""

from __future__ import annotations

from typing import Tuple

from tradingagents.tuige.rebalance_detector import RebalanceAssessment
from tradingagents.tuige.snapshot import MarketSnapshot

TUIGE_REGIMES = (
    "aggressive",
    "rotation",
    "pullback_only",
    "defensive",
    "no_trade",
)

_SETUPS_BY_REGIME = {
    "aggressive": [
        "relay-setups",
        "trend-setups",
        "limit-up-pullback-setups",
        "washout-breakout-setups",
    ],
    "rotation": [
        "trend-setups",
        "limit-up-pullback-setups",
        "washout-breakout-setups",
    ],
    "pullback_only": [
        "trend-setups",
        "limit-up-pullback-setups",
        "washout-breakout-setups",
    ],
    "defensive": ["trend-setups", "washout-breakout-setups"],
    "no_trade": [],
}

_BLOCKED_BY_REBALANCE = {
    "yes": ["relay-setups"],
    "watch": ["relay-setups"],
    "no": [],
}


def _idx(snap: MarketSnapshot, key: str, default: float = 0.0) -> float:
    return float(snap.index_changes.get(key, default))


def detect_base_regime(snap: MarketSnapshot) -> Tuple[str, str]:
    """Return (regime, rationale)."""
    sh = _idx(snap, "shanghai")
    chinext = _idx(snap, "chinext")
    star50 = _idx(snap, "star50")
    breadth = snap.advancers
    decl = snap.decliners

    if sh <= -1.5 and breadth < 1200:
        return "no_trade", "大盘明显下压且广度弱"
    if sh <= -1.0 or (decl > breadth * 1.3 and sh < 0):
        return "defensive", "指数偏弱或跌多涨少"
    if breadth >= 3500 and sh >= 0 and chinext >= 0 and star50 >= 0:
        return "aggressive", "指数与成长同步强、广度高"
    if breadth >= 3000 and sh >= 0 and (chinext < -0.3 or star50 < -0.3):
        return "rotation", "普涨但成长指数偏弱（抽血式结构）"
    if sh < 0.2 and chinext < 0:
        return "pullback_only", "承接一般，仅适合回调确认"
    if breadth >= 2500 and sh >= -0.3:
        return "rotation", "有轮动但非全面进攻"
    return "defensive", "默认保守"


def apply_rebalance_modifier(base_regime: str, rebalance: RebalanceAssessment) -> str:
    if rebalance.window == "no":
        return base_regime
    if base_regime == "aggressive":
        return "rotation"
    if rebalance.window == "yes" and base_regime == "rotation":
        return "rotation"
    if rebalance.window == "yes" and base_regime in ("pullback_only", "defensive"):
        return base_regime
    return base_regime


def allowed_setups(regime: str, rebalance_window: str) -> list[str]:
    base = list(_SETUPS_BY_REGIME.get(regime, []))
    blocked = set(_BLOCKED_BY_REBALANCE.get(rebalance_window, []))
    return [s for s in base if s not in blocked]


def blocked_setups(regime: str, rebalance_window: str) -> list[str]:
    allowed = set(allowed_setups(regime, rebalance_window))
    all_setups = set(_SETUPS_BY_REGIME["aggressive"])
    return sorted(all_setups - allowed)


def position_cap_for_regime(regime: str, rebalance_window: str) -> str:
    if regime == "no_trade":
        return "no_trade"
    if rebalance_window == "yes":
        return "light"
    if regime == "aggressive":
        return "standard"
    if regime in ("rotation", "pullback_only"):
        return "light"
    return "defensive"
