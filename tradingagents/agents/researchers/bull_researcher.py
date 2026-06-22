from tradingagents.agents.utils.agent_utils import get_language_instruction
from tradingagents.agents.utils.past_context import past_context_prompt_block
from tradingagents.agents.utils.position_context import get_position_assumption_instruction
from tradingagents.agents.utils.verified_facts import append_verified_market_facts
from tradingagents.graph.debate_context import (
    format_investment_debate_history,
    maybe_refresh_investment_summary,
)


def _safe_report(text: str) -> str:
    cleaned = (text or "").strip()
    return cleaned if cleaned else "(This report was not generated or is unavailable for this run. Do NOT assume, fabricate, or speculate on any facts, metrics, or announcements from this category.)"


def create_bull_researcher(llm):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        raw_history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")
        current_response = investment_debate_state.get("current_response", "")
        market_research_report = _safe_report(state["market_report"])
        sentiment_report = _safe_report(state["sentiment_report"])
        news_report = _safe_report(state["news_report"])
        fundamentals_report = _safe_report(state["fundamentals_report"])
        asset_type = state.get("asset_type", "stock")
        target_label = "stock" if asset_type == "stock" else "asset"
        fundamentals_label = (
            "Company fundamentals report"
            if asset_type == "stock"
            else "Asset fundamentals report (may be unavailable for crypto)"
        )
        debate_context = format_investment_debate_history(state, llm)
        quality_notes = (state.get("report_quality_notes") or "").strip()
        quality_block = f"\n\n{quality_notes}\n" if quality_notes else ""

        prompt = f"""You are a Bull Analyst advocating for investing in the {target_label}. Your task is to build a strong, evidence-based case emphasizing growth potential, competitive advantages, and positive market indicators. Leverage the provided research and data to address concerns and counter bearish arguments effectively.

Key points to focus on:
- Preemptive Causal Clues & Chokepoint Identification (卡脖子瓶颈与蛛丝马迹的先导推演): Actively apply Serenity's "Chokepoint Theory". Search the analyst reports and fundamentals for niche, irreplaceable upstream physical bottlenecks (e.g. rare raw materials, specialized substrates like InP, specific testing equipment, or precision packaging technologies) that downstream giants must rely on. Map out the causal chain and transmission lag.
- Serenity Evidence Pyramid (Serenity 证据金字塔约束): Restrict your arguments strictly to high-credibility sources:
  * [S-Tier / L1]: SEC financial reports, official corporate announcements, management minutes, QVL certification lists.
  * [A-Tier / L2 (Physical Anomalies)]: Specialized job hiring spikes (e.g. advanced packaging engineers), new patent publications, peer Capex expansion, state CHIPS Act funding.
  * Clearly label any [L3/L4] rumors or model extrapolations and explain how they link to L1/L2 hard facts.
- Value Chain & Peer Transmission (顺藤摸瓜的价值链与个股联动推演): Benchmark this company against the '同业对照' (peer valuation) table. If peers or the broader sector are rising on high volume, argue how sector rotation or supply-chain demand will pull ('顺藤摸瓜') this stock's valuation upward. Identify specific bottleneck links where upstream/downstream trends will directly transmit as positive triggers.
- Growth Potential & Competitive Advantages: Highlight market opportunities, unique technologies, pricing power, high switching costs, and gross margin resilience.
- Bear Counterpoints: Critically analyze the bear argument with specific data and sound reasoning, addressing concerns thoroughly and showing why the bull perspective holds stronger merit.
- Engagement: Present your argument in a conversational style, engaging directly with the bear analyst's points and debating effectively rather than just listing data.
- Cite which analyst report section supports each claim; do not rely on low-quality flagged reports.

Resources available:
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
{quality_block}
Conversation history of the debate: {debate_context}
Last bear argument: {current_response}
Use this information to deliver a compelling bull argument, refute the bear's concerns, and engage in a dynamic debate that demonstrates the strengths of the bull position.
""" + past_context_prompt_block(state.get("past_context", ""), "bull_researcher") + get_position_assumption_instruction() + get_language_instruction()

        prompt = append_verified_market_facts(prompt, state)
        response = llm.invoke(prompt)

        argument = f"Bull Analyst: {response.content}"
        summary = maybe_refresh_investment_summary(state, llm)

        new_investment_debate_state = {
            "history": raw_history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "summary": summary,
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
