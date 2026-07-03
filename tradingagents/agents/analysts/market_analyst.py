from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_indicators,
    get_language_instruction,
    get_stock_data,
)
from tradingagents.agents.utils.analyst_output_format import (
    ANALYST_REPORT_SECTIONS,
    EVIDENCE_TIER_RULES,
)
from tradingagents.agents.utils.analyst_threads import (
    analyst_invoke_messages,
    analyst_node_return,
)
from tradingagents.dataflows.cn_prefetch import get_prefetched
from tradingagents.dataflows.config import get_config
from tradingagents.market import cn_uses_a_share_skill, normalize_a_share_code


_CN_MARKET_RULES = """
## A 股技术面纪律
- 考虑涨跌停（±10%/±20%）、T+1、ST、科创板/创业板规则对信号的影响。
- 量价须结合：缩量反弹 vs 放量突破；北向/主力资金流向（若有预取块）须交叉验证。
- 估值数字（PE/PB/现价）只能引用下方预取/硬数据，禁止估算。
"""

_US_INDICATOR_CATALOG = """
Moving Averages:
- close_50_sma: 50 SMA: medium-term trend
- close_200_sma: 200 SMA: long-term benchmark
- close_10_ema: 10 EMA: short-term momentum
MACD: macd, macds, macdh
Momentum: rsi
Volatility: boll, boll_ub, boll_lb, atr
Volume: vwma
Select up to 8 complementary indicators. Call get_stock_data first, then get_indicators.
"""


def _build_cn_system_message(ticker: str, trade_date: str, prefetched: str) -> str:
    return f"""你是一名 A 股市场技术分析师。基于下方预取的 K 线/资金流数据，为 {ticker} 撰写截至 {trade_date} 的技术面报告。
禁止编造未出现在数据中的价格、指标或量能。

## 预取数据（撰写须以此为准）
{prefetched or "(预取为空 — 说明数据缺口，勿猜测)"}

{_CN_MARKET_RULES}
{EVIDENCE_TIER_RULES}
{ANALYST_REPORT_SECTIONS}
{get_language_instruction()}"""


def _build_us_system_message() -> str:
    return (
        "You are a trading assistant analyzing financial markets. Select up to 8 "
        "complementary indicators from:\n"
        + _US_INDICATOR_CATALOG
        + "\nWrite a detailed trend report with actionable insights."
        + EVIDENCE_TIER_RULES
        + ANALYST_REPORT_SECTIONS
        + get_language_instruction()
    )


def create_market_analyst(llm, *, analyst_thread_key: str | None = None):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        asset_type = state.get("asset_type", "stock")
        instrument_context = build_instrument_context(ticker, asset_type)
        cfg = get_config()
        is_cn = cn_uses_a_share_skill(ticker, cfg)

        tools = [get_stock_data, get_indicators]

        if is_cn:
            code6 = normalize_a_share_code(ticker)
            required = {
                f"kline:{code6}": "K线",
                f"technical:{code6}": "技术指标(MA/MACD/RSI/BOLL)",
            }
            blocks = []
            for key, label in required.items():
                block = get_prefetched(key)
                if not (block or "").strip():
                    raise RuntimeError(
                        f"A-share {label} prefetch missing for {code6}; "
                        "aborting market analysis."
                    )
                blocks.append(block)
            fund_flow = get_prefetched(f"fund_flow:{code6}")
            if fund_flow:
                blocks.append(fund_flow)
            prefetched = "\n\n".join(blocks)
            system_message = _build_cn_system_message(ticker, current_date, prefetched)
            tools = []
        else:
            system_message = _build_us_system_message()

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

        if tools:
            chain = prompt | llm.bind_tools(tools)
        else:
            chain = prompt | llm
        result = chain.invoke(analyst_invoke_messages(state, analyst_thread_key))

        report = ""
        if not getattr(result, "tool_calls", None):
            report = result.content

        return analyst_node_return(
            state,
            thread_key=analyst_thread_key,
            message=result,
            report_key="market_report",
            report=report,
        )

    return market_analyst_node
