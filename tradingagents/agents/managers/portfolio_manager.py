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
from tradingagents.agents.utils.position_context import (
    get_rating_scale_guidance,
    is_retail_position,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.agents.utils.verified_facts import append_verified_market_facts


def _build_gatekeeping_mandate() -> str:
    """Return the fact-auditing mandate block adapted to position context."""
    if is_retail_position():
        return """## 【决策框架：机构定价逻辑 × 个人交易纪律】

你的核心优势是**利用机构的定价约束来寻找个人交易窗口**。
机构的 L1/L2/L3/L4 分析、同业比价、时滞评估最终体现在买卖决策上，从而驱动股价。
你需要理解他们的逻辑链，然后判断：**现在是上车、等待、还是回避？**

### 一、证据分级（保留判断力底线）
1. **证据分级与打假**：区分 L1/L2（事实/审阅报告/监管公告/财务数据）与 L3/L4（传闻/猜测/情绪）。优先采信 L1/L2 证据，对 L3/L4 来源的推论要求交叉验证，否决明显幻觉。
2. **逻辑跳跃惩罚**：若分析师从微弱线索推导出过度乐观结论，需对其论点评级降权。

### 二、机构定价逻辑——三透镜评估供需压力
评估以下因素不是为「合规」，而是为了判断**边际定价者（机构）会怎么行动，从而影响股价**：

**透镜①：同业比价 → 溢价空间 vs 估值天花板**
- 机构做跨股票配置，当标的与可比同业的估值持平甚至更高时，机构不愿溢价买入 → 缺乏增量资金 → 股价短期难涨
- 但个人可以接受龙头溢价（规模效应、技术壁垒、流动性溢价），只需清楚这层溢价没有安全垫
- 决策启示：估值持平 = 等回调再考虑；估值低于同业 = 可能有估值修复空间

**透镜②：时滞 → 资金入场节奏 vs 短期卖压**
- 重资本开支/长研发周期的公司，利润兑现需数月到数年。机构在这段「失血期」内不会重仓 → 买方力量弱 → 股价上行有压力
- 但个人的资金体量小，不需要等机构建仓完毕。时滞期的低迷正是**分批吸筹的窗口**
- 决策启示：时滞越长，越应该分步建仓而非一次性买入，并严格止损

**透镜③：信息透明度 → 买方深度 vs 流动性风险**
- 信息不透明（海外子公司、关联交易、复杂股权结构）→ 机构不敢上仓位 → 买方基础薄 → 流动性差
- 流动性差意味着：你买时容易（拉高几个价位就能买到），但卖时容易被砸（买一买二挂单薄）
- 决策启示：流动性差的标的，单笔不超过计划仓位的 30%，且必须预留更宽的止损容忍度

### 三、个人交易纪律（严格执行）
4. **止损纪律**：若推荐 Buy/Overweight，必须有**明确的止损价**，最大回撤控制在 8-10% 以内。
5. **分批原则**：可以左侧建仓，但必须分步执行，单笔不超过该票计划总仓位的 50%。"""

    return """## 【Fact-Auditing & Logic Gatekeeping Mandate (事实合规与逻辑门禁)】
You are the ultimate guarantor of truth and risk discipline for the fund. When synthesizing the debate, you MUST:
1. Conduct Fact-Checking (事实比对审计): Audit all '蛛丝马迹' (preemptive clues) and causal arguments made during the debate against the official 'Verified Market Facts' block. Spot and disqualify any AI hallucinations or fabricated claims immediately.
2. Apply Credibility Discounts (可信度降权): Assess the source credibility of the evidence:
   - Completely disqualify or severely discount arguments that treat unverified [L4: Market Rumors] (forum gossip, speculative posts) as absolute truths.
   - Reward and heavily weight arguments grounded in [L1: Absolute Facts] (audited filings, regulatory reports) and [L2: Physical Anomalies] (customs/job postings/procurement招标).
3. Penalize Logical Leaps (逻辑跳跃惩罚): If an analyst draws an over-optimistic conclusion from a minor clue (e.g., assuming a small trial order means they are the exclusive global supplier), discount their thesis and reduce the recommended size or downgrade the rating.
4. Scale for Lead-Time (根据时滞调整建仓节奏): Take into account the physical, compliance, and regulatory lead-times (时滞). If the transmission chain is long (e.g., waiting for multi-year regulatory audits), favor a phased, conservative accumulation (分批建仓) over immediate full-position exposure.
5. Manage Information Blackboxes (管理信息黑盒风险): If any upstream analyst or researcher explicitly flags an 'Information Gap' (数据黑盒) or high transmission risk (传导链由于信息/财务不透明无法完全闭环), treat this opacity as a critical risk factor. Conservatively downsize your proposed transaction and downgrade the rating accordingly, rather than assuming success.
6. Verify Value Chain & Peer Transmission (校对价值链与同业比价传导): Evaluate the validity of any '顺藤摸瓜' (value chain or co-movement) arguments made during the debate. Compare the stock's valuation to the '同业对照' (peer valuation) table in the verified facts block. Disqualify speculative arguments claiming automatic valuation-parity rises unless the stock shows genuine competitive advantage or a solid transmission mechanism (e.g. rising orders resulting from peer supply bottlenecks). Ensure high-valuation 'gengfeng' (跟风) laggards are heavily penalized."""


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

        gatekeeping = _build_gatekeeping_mandate()
        prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

{instrument_context}

---

{get_rating_scale_guidance()}

---

{gatekeeping}

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
