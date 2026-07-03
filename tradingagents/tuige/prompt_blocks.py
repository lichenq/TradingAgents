"""LLM prompt blocks for Tuige regime + rebalance context."""

from __future__ import annotations

from typing import Any


def get_regime_prompt_instructions(regime: str) -> str:
    """Prompt discipline for the effective Tuige regime."""
    if regime == "aggressive":
        return """
=========================================
【Tuige 市场环境：aggressive — 激进/主线共振】
1. 允许评估趋势延续、涨停后整理、洗盘末端；接力类仅在有梯队与承接时考虑。
2. 可对强趋势给予一定估值容忍，但须写清 trigger 与 invalidation。
3. 防爆底线：TMN PE>80x 且增速<50% 仍一票否决；偏离 MA30>25% 禁止追高建仓。
=========================================
"""
    if regime == "rotation":
        return """
=========================================
【Tuige 市场环境：rotation — 轮动】
1. 允许有辨识度的个股，但不追最极端的情绪扩张与日内切换主线。
2. 禁止因板块单日资金流入就给出 Buy；需结构 trigger 确认。
3. 接力逻辑默认不启用；优先 trend-setups / limit-up-pullback-setups。
=========================================
"""
    if regime == "pullback_only":
        return """
=========================================
【Tuige 市场环境：pullback_only — 仅回调确认】
1. 只允许缩量回踩、涨停后整理完好、洗盘末端确认后的再起。
2. 无 trigger 一律 Hold/观望；禁止突破追入。
3. 仓位建议上限：light。
=========================================
"""
    if regime == "defensive":
        return """
=========================================
【Tuige 市场环境：defensive — 防御】
1. 以观察与轻仓试错为主；评级上限倾向 Hold，开仓需极强证据。
2. 禁止情绪策略与左侧接飞刀；强调绝对安全边际。
3. 仓位建议：defensive 或 no_trade。
=========================================
"""
    if regime == "no_trade":
        return """
=========================================
【Tuige 市场环境：no_trade — 不建议交易】
1. 默认不给出新建仓 Buy/Overweight；仅做记录或持仓风控讨论。
2. 若用户已有持仓，可讨论减仓与失效条件，但不扩大风险暴露。
=========================================
"""
    return ""


def format_tuige_prompt_block(ctx: Any) -> str:
    if not ctx.enabled:
        return ""

    lines = [
        "=========================================",
        "【Tuige 短线纪律 — 退哥体系可执行摘要】",
        f"- 基础环境: {ctx.base_regime}",
        f"- 有效环境: {ctx.effective_regime}",
        f"- 机构换仓窗口: {ctx.rebalance_window}",
    ]
    if ctx.signal_hits:
        lines.append(f"- 换仓信号: {', '.join(ctx.signal_hits)}")
    if ctx.allowed_setups:
        lines.append(f"- 允许场景: {', '.join(ctx.allowed_setups)}")
    if ctx.blocked_setups:
        lines.append(f"- 禁止场景: {', '.join(ctx.blocked_setups)}")
    lines.append(f"- 仓位上限参考: {ctx.position_cap}")
    setup = getattr(ctx, "tuige_setup", None)
    if setup:
        lines.append(f"- 个股场景分类: {setup}")
        if getattr(ctx, "tuige_setup_rationale", None):
            lines.append(f"- 场景依据: {ctx.tuige_setup_rationale}")
    if ctx.rebalance_note:
        lines.append(f"- 换仓说明: {ctx.rebalance_note}")
    for rem in ctx.reminders:
        lines.append(f"- 提醒: {rem}")
    lines.append("=========================================")
    return "\n".join(lines) + "\n"


def format_setup_prompt_block(setup: str) -> str:
    """Per-ticker setup discipline for Stage-2 debate."""
    if not setup or setup == "unclassified":
        return ""

    blocks = {
        "trend-setups": """
=========================================
【Tuige 个股场景：trend-setups — 趋势回踩】
1. 评估 MA 支撑、缩量回踩、再起 trigger；禁止在趋势破坏后强行猜底。
2. 失效：有效跌破关键均线且无法收回。
3. 禁止把单日脉冲当趋势延续。
=========================================
""",
        "limit-up-pullback-setups": """
=========================================
【Tuige 个股场景：limit-up-pullback-setups — 涨停后整理】
1. 关注涨停阳关键低点是否完好；整理末端需 trigger 确认。
2. 失效：有效跌破涨停关键低点或放量阴跌。
3. 无整理确认一律 Hold，禁止追板后无脑持有。
=========================================
""",
        "relay-setups": """
=========================================
【Tuige 个股场景：relay-setups — 接力（高风险）】
1. 仅在有强题材、梯队、承接与封板质量时评估；默认仓位 light。
2. 换仓窗口内本场景应直接 Avoid；无 trigger 禁止 Buy。
3. 失效：次日弱承接、同身位被卡、放量封不住。
=========================================
""",
        "washout-breakout-setups": """
=========================================
【Tuige 个股场景：washout-breakout-setups — 洗盘末端】
1. 等确认不猜底：缩量极致后放量突破，或假跌破快速收回。
2. 失效：下破后无法收回、突破后跌回箱体内。
3. 无量能配合的突破不予 Overweight/Buy。
=========================================
""",
    }
    return blocks.get(setup, "")
