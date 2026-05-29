from tradingagents.agents.utils.agent_utils import get_language_instruction
from tradingagents.agents.utils.position_context import get_position_assumption_instruction
from tradingagents.agents.utils.verified_facts import append_verified_market_facts


def _safe_report(text: str) -> str:
    cleaned = (text or "").strip()
    return cleaned if cleaned else "(This report was not generated or is unavailable for this run. Do NOT assume, fabricate, or speculate on any facts, metrics, or announcements from this category.)"


def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

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

        prompt = f"""You are a Bear Analyst making the case against investing in the {target_label}. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided research and data to highlight potential downsides and counter bullish arguments effectively.

Key points to focus on:
- Fact Credibility Auditing & De-bunking (可信度打假与审计): Critically analyze the bull analyst's arguments. Check if their optimistic projections are built on low-credibility sources like [L4: Market Rumors] (social media chatter, forum leaks) rather than [L1: Absolute Facts] or [L2: Physical Anomalies]. Boldly call out these logical leaps!
- Value Chain & Peer Transmission Risks (时滞与产业链传导伪命题打假): Attack the bull's '顺藤摸瓜' value-chain or sector-rotation arguments. Use the '同业对照' (peer valuation) table to show if this stock is actually a weaker laggard ('跟风盘') with deteriorating margins compared to industry leaders. Argue that upstream cost surges (e.g. raw material/energy inflation) represent severe cost transmission risk rather than high-margin growth, and highlight downstream customer weakness/demand destruction that will block any positive transmission.
- Lead-Time & Transmission Lag Obstacles (时滞与传导壁垒): Even if the bull analyst points to a genuine L1/L2 preemptive indicator (like a Capex surge), highlight the extreme physical lead-times, regulatory audits (e.g., FDA, AS9100), and pricing-power constraints that could delay or completely block these investments from turning into net earnings.
- Risks and Challenges: Highlight factors like market saturation, financial instability, or macroeconomic threats that could hinder the stock's performance.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning, declining innovation, or threats from competitors.
- Bull Counterpoints: Critically analyze the bull argument with specific data and sound reasoning, exposing weaknesses or over-optimistic assumptions.
- Engagement: Present your argument in a conversational style, directly engaging with the bull analyst's points and debating effectively rather than simply listing facts.

Resources available:
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
Conversation history of the debate: {history}
Last bull argument: {current_response}
Use this information to deliver a compelling bear argument, refute the bull's claims, and engage in a dynamic debate that demonstrates the risks and weaknesses of investing in the {target_label}.
""" + get_position_assumption_instruction() + get_language_instruction()

        prompt = append_verified_market_facts(prompt, state)
        response = llm.invoke(prompt)

        argument = f"Bear Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
