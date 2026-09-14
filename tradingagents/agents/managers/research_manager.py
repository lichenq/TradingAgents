"""Research Manager: turns the bull/bear debate into a structured investment plan for the trader."""

from __future__ import annotations

from tradingagents.agents.schemas import ResearchPlan, render_research_plan
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.past_context import past_context_prompt_block
from tradingagents.agents.utils.position_context import get_rating_scale_guidance
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.agents.utils.verified_facts import append_verified_market_facts


def create_research_manager(llm):
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")

    def research_manager_node(state) -> dict:
        # Imported here, not at module level: tradingagents.graph imports this
        # package (circular import).
        from tradingagents.graph.debate_context import format_investment_debate_history

        instrument_context = build_instrument_context(state["company_of_interest"])
        history = format_investment_debate_history(state, llm)
        quality_notes = (state.get("report_quality_notes") or "").strip()
        quality_block = f"\n\n{quality_notes}\n" if quality_notes else ""

        prompt = f"""As the Research Manager and debate facilitator, your role is to critically evaluate this round of debate and deliver a clear, actionable investment plan for the trader.

{instrument_context}

---

{get_rating_scale_guidance()}

Commit to a directional stance only when the debate's strongest arguments clearly warrant one. Choose Hold when the evidence is balanced, materially conflicting, ambiguous, or insufficient to justify changing exposure (flat portfolio: Hold means do not open); do not manufacture a direction merely to appear decisive. Weigh the bull and bear cases on their merits, independent of which side spoke first or last.

---

**Debate History:**
{history}
{quality_block}

{NO_EXTERNAL_TOOLS}""" + past_context_prompt_block(state.get("past_context", ""), "research_manager") + get_language_instruction()

        investment_debate_state = state["investment_debate_state"]

        prompt = append_verified_market_facts(prompt, state)
        investment_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Research Manager",
        )

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "summary": investment_debate_state.get("summary", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }

    return research_manager_node
