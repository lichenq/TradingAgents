from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_language_instruction,
)
from tradingagents.dataflows.config import get_config
from tradingagents.market import cn_uses_a_share_skill


_CN_DATA_RULES = (
    "\n\n【A股数据纪律 — 必须遵守】\n"
    "1. 报告中的**每一个数字**必须来自本对话中的工具返回或下方「预取基本面数据」块；"
    "引用时注明报告期、数据来源字段。\n"
    "2. 若工具返回 timeout / unavailable / 空 JSON，只写一句「实时基本面数据暂不可用」，"
    "**禁止**用模型记忆、估算或「2025年报/2026一季报」等未在工具输出中出现的数字填表。\n"
    "3. **禁止**写「数据源连接超时」后又自行编造财务表格。\n"
    "4. 优先使用预取数据；可再调用 `get_fundamentals` 核对，勿重复调用已返回相同内容的工具。"
)


def _prefetch_cn_fundamentals(ticker: str, trade_date: str) -> str:
    cfg = get_config()
    if not cn_uses_a_share_skill(ticker, cfg):
        return ""
    from tradingagents.dataflows.a_share import (
        a_share_fundamentals_failed,
        get_a_share_fundamentals,
    )
    from tradingagents.dataflows.cn_prefetch import get_prefetched
    from tradingagents.market import normalize_a_share_code

    code6 = normalize_a_share_code(ticker)
    cached = get_prefetched(f"fundamentals:{code6}")
    block = cached if cached else get_a_share_fundamentals(ticker, trade_date)
    if a_share_fundamentals_failed(block):
        return ""
    return block


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        instrument_context = build_instrument_context(ticker)
        cfg = get_config()
        is_cn = cn_uses_a_share_skill(ticker, cfg)

        prefetched = _prefetch_cn_fundamentals(ticker, current_date) if is_cn else ""

        if is_cn:
            tools = [get_fundamentals]
            tool_hint = "`get_fundamentals`（A股：东财财务摘要 / akshare 业绩，已预取则直接据此撰写）"
        else:
            tools = [
                get_fundamentals,
                get_balance_sheet,
                get_cashflow,
                get_income_statement,
            ]
            tool_hint = (
                "`get_fundamentals`, `get_balance_sheet`, `get_cashflow`, "
                "`get_income_statement`"
            )

        system_message = (
            "You are a researcher tasked with analyzing fundamental information over the past week about a company. Please write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, and company financial history to gain a full view of the company's fundamental information to inform traders. Make sure to include as much detail as possible. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + " Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."
            + f" Use the available tools: {tool_hint}."
            + get_language_instruction()
        )
        if is_cn:
            system_message += _CN_DATA_RULES
            if prefetched:
                system_message += (
                    "\n\n## 预取基本面数据（实时工具结果，撰写报告必须以此为准）\n\n"
                    + prefetched
                )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
