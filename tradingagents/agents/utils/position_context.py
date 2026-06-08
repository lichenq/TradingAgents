"""Portfolio assumption for decision agents: flat, held, or retail (individual investor)."""

from __future__ import annotations

_POSITION_EMPTY = "empty"
_POSITION_HELD = "held"
_POSITION_RETAIL = "retail"
_VALID = frozenset({_POSITION_EMPTY, _POSITION_HELD, _POSITION_RETAIL})


def get_position_context() -> str:
    from tradingagents.dataflows.config import get_config

    raw = (get_config().get("position_context") or _POSITION_EMPTY).strip().lower()
    return raw if raw in _VALID else _POSITION_EMPTY


def is_empty_position() -> bool:
    return get_position_context() == _POSITION_EMPTY


def is_retail_position() -> bool:
    return get_position_context() == _POSITION_RETAIL


def _use_chinese() -> bool:
    from tradingagents.dataflows.config import get_config

    lang = (get_config().get("output_language") or "English").strip().lower()
    return lang not in ("english", "en")


def get_position_assumption_instruction() -> str:
    """Prompt block: how to phrase actions given flat / held / retail portfolio."""
    if is_empty_position():
        if _use_chinese():
            return (
                "\n\n**仓位前提**：投资者当前**无持仓（空仓）**。所有建议均针对是否**新建仓**："
                "禁止写「减仓」「减持」「降至基准权重」等已有仓位操作；"
                "Underweight/Sell 表示**不建仓/回避**；Hold 表示**观望、不开仓**；"
                "Buy/Overweight 表示**可考虑建仓**及具体入场条件。"
            )
        return (
            "\n\n**Position assumption**: The investor is **flat (no existing position)**. "
            "Frame every recommendation as whether to **initiate** exposure: "
            "never suggest trimming, profit-taking, or benchmark weight cuts. "
            "Underweight/Sell mean **do not open / avoid entry**; Hold means **stay in cash**; "
            "Buy/Overweight mean **consider initiating** with explicit entry conditions."
        )
    if is_retail_position():
        if _use_chinese():
            return (
                "\n\n**仓位前提**：你是**个人投资者**，资金灵活、决策快速。"
                "你的核心策略是：**站在机构的逻辑链上思考，利用他们的约束窗口来交易**。"
                "理解机构怎么定价（同业比价、时滞、信息透明度），然后判断当前是上车、等待还是回避。"
                "不要求完美的右侧确认信号，但**必须设硬止损**。"
                "单只股票总仓位不超过可投资金的15%，可分3笔分批入场。"
            )
        return (
            "\n\n**Position assumption**: You are a **retail investor** with flexible capital. "
            "Your core edge: **think through the institutional pricing logic, then trade the gaps**. "
            "Understand how institutions price this stock (peer valuation, lead-times, transparency), "
            "then decide whether to enter, wait, or avoid. "
            "You can accept phased entries without perfect right-side confirmation. "
            "Strict stop-losses are required. "
            "Max single-stock exposure: 15% of total investable capital, split into 3 tranches."
        )
    if _use_chinese():
        return (
            "\n\n**仓位前提**：投资者**已持有**该标的。评级与操作建议可包含加仓、减仓、"
            "止盈止损及相对基准的权重调整。"
        )
    return (
        "\n\n**Position assumption**: The investor **already holds** this instrument. "
        "Recommendations may include add, trim, take profit, stop-loss, and benchmark-relative sizing."
    )


def get_rating_scale_guidance() -> str:
    """Rating-scale block for Research Manager and Portfolio Manager prompts."""
    if is_empty_position():
        if _use_chinese():
            return """**评级含义（空仓，五选一）**：
- **Buy**：看好，建议按条件**建仓**
- **Overweight**：偏正面，可**分批建仓**或列入重点跟踪
- **Hold**：多空均衡或缺乏边际，**观望、暂不买入**
- **Underweight**：偏谨慎，**不要建仓、勿追高**
- **Sell**：看空，**明确回避**，短期内不碰"""
        return """**Rating scale (flat / no position)** — use exactly one:
- **Buy**: Strong conviction to **initiate** a new position
- **Overweight**: Favorable outlook; **start or scale in** with a clear plan
- **Hold**: Balanced or no edge; **do not open** — wait for a better setup
- **Underweight**: Cautious; **do not initiate** — avoid chasing
- **Sell**: Bearish; **avoid entry** entirely"""

    if is_retail_position():
        if _use_chinese():
            return """**评级含义（个人投资者，五选一）**：
- **Buy**：看好，当前可直接**小额建仓**（首笔≤计划仓位的50%），严格设止损
- **Overweight**：偏正面，可**左侧分批建仓**（分3笔），每笔下浮3-5%拉开成本
- **Hold**：关注但暂不行动，设好价格预警等待触发条件
- **Underweight**：偏谨慎，**不建仓**，可挂超跌单博反弹
- **Sell**：看空，**明确回避**"""
        return """**Rating scale (retail investor)** — use exactly one:
- **Buy**: Favorable; **start a small entry now** (first tranche ≤50% of planned size), strict stop-loss
- **Overweight**: Positive outlook; **scale in on the left** in 3 tranches, entry spaced 3-5% apart
- **Hold**: Monitor but do not act; set price alerts for conditional entry triggers
- **Underweight**: Cautious; **do not enter**, may place deep pullback limit orders only
- **Sell**: Bearish; **avoid entirely**"""

    if _use_chinese():
        return """**评级含义（已有持仓，五选一）**：
- **Buy**：强烈看好，建议**加仓**
- **Overweight**：偏正面，建议**逐步加仓**
- **Hold**：维持**当前仓位**，暂不操作
- **Underweight**：偏谨慎，建议**减仓**或部分止盈
- **Sell**：看空，建议**清仓**或不再持有"""
    return """**Rating scale (existing position)** — use exactly one:
- **Buy**: Strong conviction to **add** to the position
- **Overweight**: Favorable outlook; **gradually increase** exposure
- **Hold**: **Maintain** current position; no change needed
- **Underweight**: Cautious; **trim** exposure or take partial profits
- **Sell**: Bearish; **exit** the position"""


def get_trader_action_guidance() -> str:
    """Short guidance for the Trader's Buy/Hold/Sell given position context."""
    if is_empty_position():
        if _use_chinese():
            return (
                "空仓前提下：Buy=建议建仓；Hold=观望、不买入；Sell=回避、不建仓。"
                "勿使用减仓、止盈等已有仓位话术。"
            )
        return (
            "Flat portfolio: Buy = recommend opening; Hold = stay in cash, no entry; "
            "Sell = avoid opening. Do not use trim or take-profit language."
        )
    if is_retail_position():
        if _use_chinese():
            return (
                "个人投资者：Buy=建议分批建仓（首笔≤50%）；"
                "Hold=关注但不买，设价格预警；Sell=回避。均需标注止损价。"
            )
        return (
            "Retail investor: Buy = start phasing in (first tranche ≤50%); "
            "Hold = watch but do not buy, set price alerts; Sell = avoid entirely. "
            "Always include a stop-loss price."
        )
    if _use_chinese():
        return "已有持仓：Buy=加仓；Hold=维持；Sell=减仓或清仓。"
    return "Existing position: Buy = add; Hold = maintain; Sell = reduce or exit."
