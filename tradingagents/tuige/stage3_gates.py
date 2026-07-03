"""Stage-3 deterministic gates from Tuige setup + market context."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from tradingagents.tuige.position_grade import derive_position_grade

__all__ = ["derive_position_grade", "evaluate_tuige_setup_gate"]


def evaluate_tuige_setup_gate(
    item: Dict[str, Any],
    tuige_ctx: Optional[Dict[str, Any]],
    *,
    strict: bool = False,
) -> Tuple[bool, str]:
    """Return (pass, reason). Relay on rebalance day is always hard-rejected."""
    if not tuige_ctx or not tuige_ctx.get("enabled"):
        return True, "ok"

    setup = str(item.get("tuige_setup") or "unclassified")
    rebalance = tuige_ctx.get("rebalance_window") or "no"
    allowed = set(tuige_ctx.get("allowed_setups") or [])
    blocked = set(tuige_ctx.get("blocked_setups") or [])

    if rebalance in ("yes", "watch") and setup == "relay-setups":
        return False, "换仓窗口禁止 relay-setups"

    if setup in blocked:
        if strict:
            return False, f"setup={setup} 在 Tuige 禁止列表"
        return True, f"reminder: setup={setup} blocked"

    if allowed and setup not in allowed and setup != "unclassified":
        if strict:
            return False, f"setup={setup} 不在允许场景 {sorted(allowed)}"
        return True, f"reminder: setup={setup} not in allowed"

    return True, "ok"
