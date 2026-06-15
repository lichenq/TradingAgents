"""Stage-1 parameter overrides from market regime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet


@dataclass
class RegimeStage1Params:
    regime: str = "NORMAL_REGIME"
    validate_top_cap: int = 5
    blocked_strategies: FrozenSet[str] = field(default_factory=frozenset)
    min_volume_multiplier: float = 1.0
    note: str = ""


def regime_stage1_params(regime: str) -> RegimeStage1Params:
    if regime == "DEFENSIVE_REGIME":
        return RegimeStage1Params(
            regime=regime,
            validate_top_cap=3,
            blocked_strategies=frozenset({"em_hot_momentum", "em_fomo_exit"}),
            min_volume_multiplier=1.2,
            note="防御市况: 缩深度池、禁情绪策略、提高流动性门槛",
        )
    if regime == "HIGH_HEAT_REGIME":
        return RegimeStage1Params(
            regime=regime,
            validate_top_cap=5,
            blocked_strategies=frozenset(),
            min_volume_multiplier=1.0,
            note="高热度市况: 默认参数",
        )
    return RegimeStage1Params(
        regime=regime,
        validate_top_cap=4,
        blocked_strategies=frozenset(),
        min_volume_multiplier=1.0,
        note="常态市况",
    )


def detect_book_regime(trade_date: str) -> str:
    from tradingagents.agents.utils.market_regime import detect_market_regime

    return detect_market_regime("600519", trade_date)
