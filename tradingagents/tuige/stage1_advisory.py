"""Stage-1 advisory suggestions from Tuige regime (reminder mode by default)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Tuple

from tradingagents.tuige.regime import TUIGE_REGIMES


@dataclass
class Stage1Advisory:
    regime: str
    validate_top_cap: int = 5
    blocked_strategies: FrozenSet[str] = field(default_factory=frozenset)
    min_volume_multiplier: float = 1.0
    note: str = ""
    reminders: Tuple[str, ...] = ()


def stage1_advisory_for_regime(
    regime: str,
    rebalance_window: str,
) -> Stage1Advisory:
    reminders: list[str] = []

    if regime == "no_trade":
        return Stage1Advisory(
            regime=regime,
            validate_top_cap=0,
            blocked_strategies=frozenset(
                {"trend_pullback", "macd_resonance", "macd_second_golden_cross",
                 "em_hot_momentum", "em_fomo_exit"}
            ),
            note="Tuige no_trade：建议空仓观察",
            reminders=("环境不支持短线，推荐结果仅供参考",),
        )

    if regime == "defensive":
        blocked = frozenset({"em_hot_momentum", "em_fomo_exit"})
        reminders.append("防御环境：情绪/追热策略不建议使用")
        return Stage1Advisory(
            regime=regime,
            validate_top_cap=3,
            blocked_strategies=blocked,
            min_volume_multiplier=1.2,
            note="Tuige defensive：缩深度池、禁情绪策略",
            reminders=tuple(reminders),
        )

    if regime == "pullback_only":
        blocked = frozenset({"em_hot_momentum", "em_fomo_exit"})
        reminders.append("仅适合回调确认类策略，勿追日内脉冲")
        return Stage1Advisory(
            regime=regime,
            validate_top_cap=4,
            blocked_strategies=blocked,
            note="Tuige pullback_only：只允许回踩/整理确认",
            reminders=tuple(reminders),
        )

    if regime == "rotation":
        blocked: FrozenSet[str] = frozenset()
        cap = 4
        if rebalance_window in ("yes", "watch"):
            blocked = frozenset({"em_hot_momentum", "em_fomo_exit"})
            cap = 3
            reminders.append("换仓窗口：禁止接力/追热，勿因单日板块流入全仓切换")
        return Stage1Advisory(
            regime=regime,
            validate_top_cap=cap,
            blocked_strategies=blocked,
            note="Tuige rotation：轮动市，不追最极端情绪",
            reminders=tuple(reminders),
        )

    if regime == "aggressive":
        cap = 5
        if rebalance_window in ("yes", "watch"):
            cap = 3
            reminders.append("虽个股所属板块强，但全市场处换仓观察期，建议降级为 rotation 口径")
        return Stage1Advisory(
            regime=regime,
            validate_top_cap=cap,
            blocked_strategies=frozenset(),
            note="Tuige aggressive：主线共振（换仓日应自行降级）",
            reminders=tuple(reminders),
        )

    return Stage1Advisory(regime="rotation", note="未知 regime，按 rotation 提醒")


def validate_regime(regime: str) -> str:
    if regime in TUIGE_REGIMES:
        return regime
    return "rotation"
