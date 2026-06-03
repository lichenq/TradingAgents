"""Portfolio Manager: synthesises the risk-analyst debate into the final decision.

Uses LangChain's ``with_structured_output`` so the LLM produces a typed
``PortfolioDecision`` directly, in a single call.  The result is rendered
back to markdown for storage in ``final_trade_decision`` so memory log,
CLI display, and saved reports continue to consume the same shape they do
today.  When a provider does not expose structured output, the agent falls
back gracefully to free-text generation.
"""

from __future__ import annotations

from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.position_context import get_rating_scale_guidance
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.agents.utils.verified_facts import append_verified_market_facts


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions and outcomes:\n{past_context}\n"
            if past_context
            else ""
        )

        prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

{instrument_context}

---

{get_rating_scale_guidance()}

---

## 【Fact-Auditing & Logic Gatekeeping Mandate (事实合规与逻辑门禁)】
You are the ultimate guarantor of truth and risk discipline for the fund. When synthesizing the debate, you MUST:
1. Conduct Fact-Checking (事实比对审计): Audit all '蛛丝马迹' (preemptive clues) and causal arguments made during the debate against the official 'Verified Market Facts' block. Spot and disqualify any AI hallucinations or fabricated claims immediately.
2. Apply Credibility Discounts (可信度降权): Assess the source credibility of the evidence:
   - Completely disqualify or severely discount arguments that treat unverified [L4: Market Rumors] (forum gossip, speculative posts) as absolute truths.
   - Reward and heavily weight arguments grounded in [L1: Absolute Facts] (audited filings, regulatory reports) and [L2: Physical Anomalies] (customs/job postings/procurement招标).
3. Penalize Logical Leaps (逻辑跳跃惩罚): If an analyst draws an over-optimistic conclusion from a minor clue (e.g., assuming a small trial order means they are the exclusive global supplier), discount their thesis and reduce the recommended size or downgrade the rating.
4. Scale for Lead-Time (根据时滞调整建仓节奏): Take into account the physical, compliance, and regulatory lead-times (时滞). If the transmission chain is long (e.g., waiting for multi-year regulatory audits), favor a phased, conservative accumulation (分批建仓) over immediate full-position exposure.
5. Manage Information Blackboxes (管理信息黑盒风险): If any upstream analyst or researcher explicitly flags an 'Information Gap' (数据黑盒) or high transmission risk (传导链由于信息/财务不透明无法完全闭环), treat this opacity as a critical risk factor. Conservatively downsize your proposed transaction and downgrade the rating accordingly, rather than assuming success.
6. Verify Value Chain & Peer Transmission (校对价值链与同业比价传导): Evaluate the validity of any '顺藤摸瓜' (value chain or co-movement) arguments made during the debate. Compare the stock's valuation to the '同业对照' (peer valuation) table in the verified facts block. Disqualify speculative arguments claiming automatic valuation-parity rises unless the stock shows genuine competitive advantage or a solid transmission mechanism (e.g. rising orders resulting from peer supply bottlenecks). Ensure high-valuation 'gengfeng' (跟风) laggards are heavily penalized.

**Context:**
- Research Manager's investment plan: **{research_plan}**
- Trader's transaction proposal: **{trader_plan}**
{lessons_line}
**Risk Analysts Debate History:**
{history}

---

Be decisive and ground every conclusion in specific evidence from the analysts. Critically evaluate their fact-credibility and logic chain reliability.{get_language_instruction()}"""

        prompt = append_verified_market_facts(prompt, state)
        final_trade_decision = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_pm_decision,
            "Portfolio Manager",
        )

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
        }

    return portfolio_manager_node
