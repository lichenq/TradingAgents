"""Stage-1 parameter tuning from audit KPIs and failure-mode counts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tradingagents.dataflows.audit_failure_modes import failure_mode_counts
from tradingagents.dataflows.audit_feedback_gates import evaluate_strategy_audit_gate


@dataclass
class AuditStage1Tune:
    validate_top_cap: int = 99
    min_volume_multiplier: float = 1.0
    max_pe_cap: Optional[float] = None
    note: str = ""


def compute_audit_stage1_tune(
    results_dir: str | Path,
    strategy: str,
) -> AuditStage1Tune:
    tune = AuditStage1Tune()
    notes: list[str] = []

    gate = evaluate_strategy_audit_gate(results_dir, strategy)
    stats = gate.get("stats") or {}
    count = int(stats.get("count") or 0)
    win_rate = stats.get("win_rate")
    if count >= 3 and win_rate is not None and float(win_rate) < 0.45:
        tune.validate_top_cap = min(tune.validate_top_cap, 3)
        tune.min_volume_multiplier = max(tune.min_volume_multiplier, 1.15)
        notes.append(f"策略{strategy}近窗胜率{float(win_rate):.0%}")

    if not gate.get("allowed", True) and count >= 3:
        tune.validate_top_cap = min(tune.validate_top_cap, 2)
        tune.min_volume_multiplier = max(tune.min_volume_multiplier, 1.25)
        notes.append("策略门禁未通过")

    mode_counts = failure_mode_counts(results_dir, lookback_days=30)
    high_pe = int(mode_counts.get("high_pe_loss", 0))
    if high_pe >= 2:
        tune.max_pe_cap = 55.0
        notes.append(f"high_pe_loss×{high_pe}")
    if high_pe >= 4:
        tune.max_pe_cap = 45.0
    if int(mode_counts.get("overextended_loss", 0)) >= 2:
        tune.validate_top_cap = min(tune.validate_top_cap, 3)
        notes.append("overextended_loss偏多")

    tune.note = "; ".join(notes)
    return tune
