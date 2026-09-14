"""Trader: turns the Research Manager's investment plan into a concrete transaction proposal."""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import TraderProposal, render_trader_proposal
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.position_context import (
    _use_chinese,
    get_trader_action_guidance,
    is_retail_position,
)
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.agents.utils.verified_facts import append_verified_market_facts


def create_trader(llm):
    structured_llm = bind_structured(llm, TraderProposal, "Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        asset_type = state.get("asset_type", "stock")
        instrument_context = build_instrument_context(company_name, asset_type)
        investment_plan = state["investment_plan"]
        # The research plan digests the debate but loses exact price structure;
        # give the Trader the technical market report so entry/stop levels are
        # grounded in real ATR / support-resistance / current price (#1167). The
        # report is empty when the user did not select the market analyst, so
        # only offer it (and the grounding instruction) when it has content.
        market_report = (state["market_report"] or "").strip()

        if market_report:
            grounding = (
                "Ground concrete price levels (entry, stop-loss, position sizing) in the technical "
                "market report's price structure -- current price, support/resistance, ATR, and "
                "volatility -- and use the research plan for direction and strategy. "
            )
            report_section = f"Technical Market Report:\n{market_report}\n\n"
        else:
            grounding = ""
            report_section = ""

        pricing_guidance = ""
        if is_retail_position():
            if _use_chinese():
                pricing_guidance = (
                    " 评估时注意：机构的定价逻辑最终体现为买卖决策、影响股价。"
                    "理解同业比价（机构是否愿意溢价买）、时滞（利润兑现前买方力量弱）、"
                    "信息透明度（买方基础厚薄），然后判断现在是上车窗口还是需要等待。"
                )
            else:
                pricing_guidance = (
                    " Evaluate through the institutional pricing lens: peer valuation "
                    "(will institutions pay a premium?), lead-times (weak buying pressure "
                    "before profit delivery), information transparency (investor depth). "
                    "Use these to gauge whether now is a valid entry window."
                )
        user_content = (
            f"Based on a comprehensive analysis by a team of analysts, here is an investment "
            f"plan tailored for {company_name}. {instrument_context} This plan incorporates "
            f"insights from current technical market trends, macroeconomic indicators, and "
            f"social media sentiment. Use this plan as a foundation for evaluating your next "
            f"trading decision.\n\n"
            f"{report_section}"
            f"Proposed Investment Plan: {investment_plan}\n\n"
            f"Leverage these insights to make an informed and strategic decision."
            f"{pricing_guidance}"
        )
        user_content = append_verified_market_facts(user_content, state)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a trading agent analyzing market data to make investment decisions. "
                    "Based on your analysis, provide a specific recommendation to buy, sell, or hold. "
                    "Anchor your reasoning in the analysts' reports and the research plan. "
                    + grounding
                    # Entry/stop are numeric price fields. Asking for concrete
                    # levels invites a percentage ("15%"), which is not a price
                    # and fails the structured parse (#1288).
                    + "State entry price and stop-loss as absolute price levels in the "
                    "instrument's quote currency (for example 189.5), never a percentage "
                    "or a range; convert a percentage distance to the price level it "
                    "implies, or omit the field if you cannot state a number. "
                    + get_trader_action_guidance()
                    + NO_EXTERNAL_TOOLS
                    + get_language_instruction()
                ),
            },
            {"role": "user", "content": user_content},
        ]

        trader_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            messages,
            render_trader_proposal,
            "Trader",
        )

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
