"""Stage-1 parameter overrides from Tuige market regime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet

from tradingagents.tuige.context import TuigeContext
from tradingagents.tuige.stage1_advisory import stage1_advisory_for_regime


@dataclass
class RegimeStage1Params:
    regime: str = "rotation"
    validate_top_cap: int = 5
    blocked_strategies: FrozenSet[str] = field(default_factory=frozenset)
    min_volume_multiplier: float = 1.0
    note: str = ""
    reminders: tuple[str, ...] = ()


def regime_stage1_params(regime: str, rebalance_window: str = "no") -> RegimeStage1Params:
    adv = stage1_advisory_for_regime(regime, rebalance_window)
    return RegimeStage1Params(
        regime=regime,
        validate_top_cap=adv.validate_top_cap,
        blocked_strategies=adv.blocked_strategies,
        min_volume_multiplier=adv.min_volume_multiplier,
        note=adv.note,
        reminders=adv.reminders,
    )


def build_regime_stage1_from_context(ctx: TuigeContext) -> RegimeStage1Params:
    if not ctx.enabled or ctx.stage1 is None:
        return regime_stage1_params("rotation")
    adv = ctx.stage1
    return RegimeStage1Params(
        regime=ctx.effective_regime,
        validate_top_cap=adv.validate_top_cap,
        blocked_strategies=adv.blocked_strategies,
        min_volume_multiplier=adv.min_volume_multiplier,
        note=adv.note,
        reminders=adv.reminders,
    )


def apply_stage1_params(
    args,
    params: RegimeStage1Params,
    *,
    strict: bool,
    prog,
    logger,
) -> bool:
    """Apply or remind Stage1 params. Returns False if pipeline should abort (strict only)."""
    prog.step(f"Tuige 市况={params.regime}: {params.note}")
    for rem in params.reminders:
        prog.step(f"[Tuige 提醒] {rem}")

    if args.strategy in params.blocked_strategies:
        msg = f"策略 {args.strategy} 在 Tuige {params.regime} 下不建议使用"
        if strict and not args.force:
            logger.error(f"{msg}。使用 --force 强制执行。")
            return False
        prog.step(f"[Tuige 提醒] {msg}（未阻断）")

    if strict:
        if args.validate_top > params.validate_top_cap:
            prog.step(
                f"validate_top {args.validate_top} → {params.validate_top_cap} (Tuige regime)"
            )
            args.validate_top = params.validate_top_cap
        if params.min_volume_multiplier != 1.0:
            args.min_volume_amount *= params.min_volume_multiplier
            prog.step(
                f"min_volume_amount ×{params.min_volume_multiplier:.1f} (Tuige regime)"
            )
    else:
        if args.strategy in params.blocked_strategies:
            prog.step(
                f"[Tuige 提醒] 建议换策略；当前仍执行 {args.strategy}"
            )
        if args.validate_top > params.validate_top_cap:
            prog.step(
                f"[Tuige 提醒] 建议 validate_top≤{params.validate_top_cap}；"
                f"当前 {args.validate_top}"
            )

    return True
