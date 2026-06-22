from tradingagents.agents.risk_mgmt.debate_helpers import risk_reports_block
from tradingagents.agents.utils.agent_utils import get_language_instruction
from tradingagents.agents.utils.position_context import get_position_assumption_instruction
from tradingagents.agents.utils.verified_facts import append_verified_market_facts
from tradingagents.graph.debate_context import (
    format_risk_debate_history,
    maybe_refresh_risk_summary,
)


def create_conservative_debator(llm):
    def conservative_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        raw_history = risk_debate_state.get("history", "")
        conservative_history = risk_debate_state.get("conservative_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")
        debate_context = format_risk_debate_history(state, llm)
        quality_notes = (state.get("report_quality_notes") or "").strip()
        quality_block = f"\n{quality_notes}\n" if quality_notes else ""
        trader_decision = state["trader_investment_plan"]

        prompt = f"""As the Conservative Risk Analyst, your primary objective is to protect assets, minimize volatility, and ensure steady, reliable growth. You prioritize stability, security, and risk mitigation, carefully assessing potential losses, economic downturns, and market volatility. 

You must act as a strict Fact & Credibility Auditor:
- Reject Weak Evidence (打假与降权): Critically analyze the trader's plan and the Aggressive Analyst's arguments. Call out any reliance on unverified [L4: Market Rumors] (e.g., social media chatter, speculative blog posts) instead of solid [L1: Absolute Facts] (audited reports, filings) or [L2: Physical Anomalies] (official customs/job/procurement filings).
- Focus on Lead-Time & Regulatory Bottlenecks (关注时滞与审查壁垒): Emphasize that even with genuine L1/L2 anomalies (like a Capex spike), the actual physical lead-time, customer audit/qualification (e.g., AS9100, FDA phase III), and pricing-power constraints mean these investments may take months or years to yield earnings, with massive execution risk in between.
- Macro Stress-Testing (进行极端压力测试): Point out macroeconomic/geopolitical threats (e.g., shipping index CCFI/BDI surges, raw material price hikes, geo-political bottlenecks) and simulate how they could severely impact the firm's margins.

Here is the trader's decision:

{trader_decision}

Your task is to actively counter the arguments of the Aggressive and Neutral Analysts, highlighting where their views may overlook potential threats, ignore physical lead-times, or rely on weak/unverified evidence. Respond directly to their points, drawing from the following data sources to build a convincing case for a low-risk approach adjustment to the trader's decision:

{risk_reports_block(state)}
{quality_block}
Here is the current conversation history: {debate_context} Here is the last response from the aggressive analyst: {current_aggressive_response} Here is the last response from the neutral analyst: {current_neutral_response}. If there are no responses from the other viewpoints yet, present your own argument based on the available data.

Engage by questioning their optimism, auditing their fact-credibility, and emphasizing the potential downsides they may have overlooked. Address each of their counterpoints to showcase why a conservative stance is ultimately the safest path for the firm's assets. Focus on debating and critiquing their arguments to demonstrate the strength of a low-risk strategy over their approaches. Output conversationally as if you are speaking without any special formatting.""" + get_position_assumption_instruction() + get_language_instruction()

        prompt = append_verified_market_facts(prompt, state)
        response = llm.invoke(prompt)

        argument = f"Conservative Analyst: {response.content}"
        summary = maybe_refresh_risk_summary(state, llm)

        new_risk_debate_state = {
            "history": raw_history + "\n" + argument,
            "summary": summary,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": conservative_history + "\n" + argument,
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Conservative",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": argument,
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return conservative_node
