"""Sentiment analyst — multi-source sentiment analysis for a target ticker.

US: Yahoo news + StockTwits + Reddit.
CN: company news + 雪球讨论 + 事件/舆情热度 (a-share-data skill).

See: https://github.com/TauricResearch/TradingAgents/issues/557
"""

from datetime import datetime, timedelta

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
    get_news,
)
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.cn_sentiment import (
    fetch_events_block,
    fetch_xueqiu_block,
)
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages
from tradingagents.agents.utils.analyst_threads import (
    analyst_invoke_messages,
    analyst_node_return,
)
from tradingagents.market import effective_market_profile


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm, *, analyst_thread_key: str | None = None):
    """Create a sentiment analyst node for the trading graph."""

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        config = get_config()
        market = effective_market_profile(ticker, config)
        instrument_context = build_instrument_context(ticker)
        if market == "cn":
            instrument_context += (
                " A-share context: T+1 settlement, ±10% price limits (±20% on ChiNext/STAR), "
                "ST/*ST risk labels, and mainland trading calendar apply."
            )

        if market == "cn":
            news_block = get_news.func(ticker, start_date, end_date)
            xueqiu_block = fetch_xueqiu_block(ticker)
            events_block = fetch_events_block(ticker, trade_date=end_date)
            system_message = _build_cn_system_message(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                news_block=news_block,
                xueqiu_block=xueqiu_block,
                events_block=events_block,
            )
        else:
            news_block = get_news.func(ticker, start_date, end_date)
            stocktwits_block = fetch_stocktwits_messages(ticker, limit=30)
            reddit_block = fetch_reddit_posts(ticker)
            system_message = _build_us_system_message(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                news_block=news_block,
                stocktwits_block=stocktwits_block,
                reddit_block=reddit_block,
            )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    "\n{system_message}\n"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm
        result = chain.invoke(analyst_invoke_messages(state, analyst_thread_key))

        return analyst_node_return(
            state,
            thread_key=analyst_thread_key,
            message=result,
            report_key="sentiment_report",
            report=result.content,
        )

    return sentiment_analyst_node


def _build_us_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> str:
    return f"""You are a financial market sentiment analyst. Produce a comprehensive sentiment report for {ticker} from {start_date} to {end_date}.

## Data sources (pre-fetched)

### News — Yahoo Finance
<start_of_news>
{news_block}
<end_of_news>

### StockTwits
<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

### Reddit
<start_of_reddit>
{reddit_block}
<end_of_reddit>

Analyze cross-source divergences, engagement-weighted Reddit signal, and StockTwits bullish/bearish ratios.
End with a Markdown table of key signals.

{get_language_instruction()}"""


def _build_cn_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    xueqiu_block: str,
    events_block: str,
) -> str:
    return f"""你是一名 A 股市场情绪分析师。请基于下列已预取的真实数据，为 {ticker} 撰写 {start_date} 至 {end_date} 的情绪报告。禁止编造未出现在数据块中的帖子、新闻或热度排名。

## 数据来源（已预取）

### 个股新闻与公告摘要
<start_of_news>
{news_block}
<end_of_news>

### 雪球讨论 — xueqiu.com 个股讨论流
散户与机构投资者观点、叙事与分歧。注意点赞/评论数代表关注度。
<start_of_xueqiu>
{xueqiu_block}
<end_of_xueqiu>

### 事件与舆情热度 — 业绩/监管/增减持/东财热度/百度热搜等
<start_of_events>
{events_block}
<end_of_events>

## 分析要点

1. 对比「新闻/公告」与「雪球讨论」是否一致；不一致本身即是信号。
2. 舆情热度方向（上升/下降/持平）需结合样本条数说明置信度。
3. 区分「事实事件」（业绩、监管、合同）与「观点表达」（雪球帖文）。
4. 考虑 A 股规则：涨跌停、T+1、ST、板块轮动对情绪的约束。
5. 情绪结论供交易团队参考，不是价格预测。

## 输出结构

1. **整体情绪**：偏多 / 偏空 / 中性 / 分化，附置信度说明。
2. **分源解读**：新闻、雪球、事件/热度各一段，引用具体证据。
3. **交叉验证**：一致点、分歧点、主导叙事。
4. **催化与风险**：未来 1–2 周可能改变情绪的因素。
5. 文末 **Markdown 表格** 汇总关键信号。

{get_language_instruction()}"""


def create_social_media_analyst(llm):
    import warnings

    warnings.warn(
        "create_social_media_analyst is deprecated. Use create_sentiment_analyst instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
