"""Dynamic audit KPI block for Portfolio Manager prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from tradingagents.dataflows.audit_feedback_gates import (
    audit_gate_config,
    evaluate_strategy_audit_gate,
)
from tradingagents.dataflows.backtest_audit_context import audit_win_rate_summary
from tradingagents.dataflows.audit_failure_modes import format_failure_mode_summary


def format_audit_kpi_mandate(
    results_dir: str | Path,
    *,
    strategy: Optional[str] = None,
) -> str:
    """Build PM-facing dynamic thresholds from recent audit performance."""
    stats = audit_win_rate_summary(results_dir, limit=30)
    lines = ["## 动态审计 KPI（须纳入最终评级）"]

    if stats["count"]:
        wr = stats["win_rate"]
        ar = stats["avg_return"]
        wr_s = f"{wr:.0%}" if wr is not None else "N/A"
        ar_s = f"{ar:+.1%}" if ar is not None else "N/A"
        lines.append(
            f"- 近 {stats['count']} 次推荐后验：胜率={wr_s}，平均收益={ar_s}"
        )
        cfg = audit_gate_config()
        min_wr = cfg["min_win_rate"]
        if wr is not None and wr < min_wr:
            lines.append(
                f"- **降档规则**：胜率低于 {min_wr:.0%} 时，默认将 Buy/Overweight "
                "降一档；无强 L1/L2 新证据不得维持激进评级。"
            )
        if ar is not None and ar < 0:
            lines.append(
                "- **负 alpha 环境**：优先 Hold/Underweight，强调防守与止损。"
            )
        fail_summary = format_failure_mode_summary(results_dir, lookback_days=30, top_n=3)
        if fail_summary:
            lines.append(f"- **{fail_summary}**")
    else:
        lines.append("- 暂无足够审计样本；仍须遵守 verified facts 与证据分级。")

    if strategy:
        gate = evaluate_strategy_audit_gate(results_dir, strategy)
        if not gate.get("allowed", True):
            lines.append(
                f"- **策略门禁**：`{strategy}` 近窗表现不达标，"
                "本 run 默认倾向 Underweight/Sell，除非硬数据明确反转。"
            )
        elif gate.get("stats", {}).get("win_rate") is not None:
            wr = gate["stats"]["win_rate"]
            lines.append(f"- 策略 `{strategy}` 近窗胜率={wr:.0%}")

    lines.append(
        "- 引用 past lessons 时须说明与本票的相关性；"
        "不得因单一失败案例机械降档。"
    )
    return "\n".join(lines)
