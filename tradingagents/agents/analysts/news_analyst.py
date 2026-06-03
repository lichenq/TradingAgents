from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_language_instruction,
    get_news,
)
from tradingagents.agents.utils.analyst_threads import (
    analyst_invoke_messages,
    analyst_node_return,
)
from tradingagents.dataflows.config import get_config


_P_COCT_NEWS_RULES = (
    "\n\n## 【Universal P-CoCT & Source Credibility Rules】\n"
    "1. Strict Anti-Hallucination: Every news item, '蛛丝马迹' (clue), or event you report MUST come from the tool output (e.g., get_news, get_global_news). Never invent news stories, corporate partnerships, or announcements.\n"
    "2. Source Credibility Grading (等级与源头标注): You MUST explicitly classify and label every news/macro clue you report with its credibility tier:\n"
    "   - [L1: Absolute Facts] (绝对事实): Official corporate exchange regulatory filings, government gazettes.\n"
    "   - [L2: Physical Anomalies] (物理异动): Customs import/export statistics, official corporate job postings, bidding/tender winner notices.\n"
    "   - [L3: Professional Reports] (专业研报): Renowned media in-depth signed investigative reports (Bloomberg, Reuters, Caixin, CLS), prominent broker research.\n"
    "   - [L4: Market Rumors] (市场传言): Internet forum leaks, social media posts, unverified blog rumors. (L4 can only be used as sentiment indicator, NEVER as fact to support critical causal chains!).\n"
    "3. Macro & Geopolitical Causal Inference (先导宏观推演): Do not just summarize news. Identify leading anomalies or macro changes (e.g., supply chain disruptions, geopolitical blockades, shipping index CCFI/BDI surges). Map out the multi-stage causal chain to show how these macro factors translate (with lags/时滞) into material micro impacts on the company's cost structure, suppliers, or customer demand.\n"
)


def create_news_analyst(llm, *, analyst_thread_key: str | None = None):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = build_instrument_context(
            state["company_of_interest"], asset_type
        )

        tools = [
            get_news,
            get_global_news,
        ]

        system_message = (
            f"You are a news researcher tasked with analyzing recent news and trends over the past week. Please write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics. Use the available tools: get_news(ticker, start_date, end_date) for {asset_label}-specific news, and get_global_news(curr_date, look_back_days, limit, ticker=<same symbol>) for a small set of macro headlines plus the ticker's industry (on A-share runs) — not a full scan of every sector board. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
            + _P_COCT_NEWS_RULES
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
        result = chain.invoke(analyst_invoke_messages(state, analyst_thread_key))

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return analyst_node_return(
            state,
            thread_key=analyst_thread_key,
            message=result,
            report_key="news_report",
            report=report,
        )

    return news_analyst_node
