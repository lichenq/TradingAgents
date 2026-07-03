"""Unified Tuige context builder for recommend + analyze pipelines."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tradingagents.dataflows.config import get_config
from tradingagents.tuige.prompt_blocks import format_tuige_prompt_block, get_regime_prompt_instructions
from tradingagents.tuige.rebalance_detector import RebalanceAssessment, detect_rebalance_window
from tradingagents.tuige.regime import (
    allowed_setups,
    apply_rebalance_modifier,
    blocked_setups,
    detect_base_regime,
    position_cap_for_regime,
)
from tradingagents.tuige.snapshot import MarketSnapshot, merge_index_payload, snapshot_from_quotes
from tradingagents.tuige.stage1_advisory import Stage1Advisory, stage1_advisory_for_regime

logger = logging.getLogger(__name__)


def tuige_enabled() -> bool:
    cfg = get_config()
    raw = os.environ.get("TRADINGAGENTS_TUIGE_ENABLED")
    if raw is not None:
        return raw.strip().lower() not in ("0", "false", "no", "off")
    return bool(cfg.get("tuige_enabled", True))


def tuige_strict() -> bool:
    cfg = get_config()
    raw = os.environ.get("TRADINGAGENTS_TUIGE_STRICT")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return bool(cfg.get("tuige_strict", False))


def _manual_regime_override() -> Optional[str]:
    raw = (get_config().get("position_context_regime") or "").strip().lower()
    mapping = {
        "aggressive": "aggressive",
        "high_heat": "aggressive",
        "rotation": "rotation",
        "pullback_only": "pullback_only",
        "pullback": "pullback_only",
        "defensive": "defensive",
        "conservative": "defensive",
        "no_trade": "no_trade",
    }
    if raw in mapping:
        return mapping[raw]
    if raw == "auto":
        return None
    return None


def _is_cn_market() -> bool:
    profile = (get_config().get("market_profile") or "us").strip().lower()
    return profile in ("cn", "a", "a_share", "china")


@dataclass
class TuigeContext:
    enabled: bool = True
    trade_date: str = ""
    ticker: Optional[str] = None
    base_regime: str = "rotation"
    effective_regime: str = "rotation"
    base_rationale: str = ""
    rebalance_window: str = "no"
    signal_hits: List[str] = field(default_factory=list)
    rebalance_note: str = ""
    allowed_setups: List[str] = field(default_factory=list)
    blocked_setups: List[str] = field(default_factory=list)
    position_cap: str = "light"
    stage1: Optional[Stage1Advisory] = None
    reminders: List[str] = field(default_factory=list)
    strict: bool = False
    tuige_setup: Optional[str] = None
    tuige_setup_rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "trade_date": self.trade_date,
            "ticker": self.ticker,
            "base_regime": self.base_regime,
            "effective_regime": self.effective_regime,
            "base_rationale": self.base_rationale,
            "rebalance_window": self.rebalance_window,
            "signal_hits": list(self.signal_hits),
            "rebalance_note": self.rebalance_note,
            "allowed_setups": list(self.allowed_setups),
            "blocked_setups": list(self.blocked_setups),
            "position_cap": self.position_cap,
            "strict": self.strict,
            "stage1_advisory": {
                "validate_top_cap": self.stage1.validate_top_cap if self.stage1 else 5,
                "blocked_strategies": sorted(self.stage1.blocked_strategies) if self.stage1 else [],
                "min_volume_multiplier": self.stage1.min_volume_multiplier if self.stage1 else 1.0,
                "note": self.stage1.note if self.stage1 else "",
            },
            "reminders": list(self.reminders),
            "tuige_setup": self.tuige_setup,
            "tuige_setup_rationale": self.tuige_setup_rationale,
        }

    def prompt_block(self) -> str:
        return format_tuige_prompt_block(self)

    def regime_prompt(self) -> str:
        return get_regime_prompt_instructions(self.effective_regime)


def build_tuige_context(
    trade_date: str,
    *,
    ticker: Optional[str] = None,
    quotes: Optional[List[Dict[str, Any]]] = None,
    index_payload: Optional[Dict[str, Any]] = None,
    industry_flows: Optional[List[Dict[str, Any]]] = None,
    tuige_setup: Optional[str] = None,
    tuige_setup_rationale: str = "",
) -> TuigeContext:
    strict = tuige_strict()
    if not tuige_enabled() or not _is_cn_market():
        return TuigeContext(
            enabled=False,
            trade_date=trade_date,
            ticker=ticker,
            strict=strict,
        )

    snap = snapshot_from_quotes(trade_date, quotes or [], industry_flows=industry_flows)
    if index_payload:
        snap = merge_index_payload(snap, index_payload)

    override = _manual_regime_override()
    if override:
        base_regime, rationale = override, f"manual override={override}"
    else:
        base_regime, rationale = detect_base_regime(snap)

    rebalance: RebalanceAssessment = detect_rebalance_window(snap)
    effective = apply_rebalance_modifier(base_regime, rebalance)

    stage1 = stage1_advisory_for_regime(effective, rebalance.window)
    reminders = list(stage1.reminders)
    if rebalance.note:
        reminders.append(rebalance.note)
    if not strict:
        reminders.append("Tuige 提醒模式：以下建议不阻断 recommend/analyze 流水线")

    ctx = TuigeContext(
        enabled=True,
        trade_date=trade_date,
        ticker=ticker,
        base_regime=base_regime,
        effective_regime=effective,
        base_rationale=rationale,
        rebalance_window=rebalance.window,
        signal_hits=list(rebalance.signal_hits),
        rebalance_note=rebalance.note,
        allowed_setups=allowed_setups(effective, rebalance.window),
        blocked_setups=blocked_setups(effective, rebalance.window),
        position_cap=position_cap_for_regime(effective, rebalance.window),
        stage1=stage1,
        reminders=reminders,
        strict=strict,
        tuige_setup=tuige_setup,
        tuige_setup_rationale=tuige_setup_rationale,
    )

    logger.info(
        "Tuige context: base=%s effective=%s rebalance=%s hits=%s",
        ctx.base_regime,
        ctx.effective_regime,
        ctx.rebalance_window,
        ctx.signal_hits,
    )
    return ctx


def fetch_market_inputs_for_tuige(trade_date: str) -> tuple[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """Best-effort index + industry fund flow for book-level Tuige context."""
    try:
        from tradingagents.tuige.market_inputs import fetch_tuige_market_inputs

        payload = fetch_tuige_market_inputs(trade_date, include_quotes=False)
        return payload.index_payload, payload.industry_flows
    except Exception as exc:
        logger.warning("Tuige market fetch skipped: %s", exc)
        return None, None
