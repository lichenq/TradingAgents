"""Inject pre-fetched market hard data into debate / decision prompts."""

from __future__ import annotations

from tradingagents.agents.utils.market_regime import detect_market_regime, get_regime_prompt_instructions

CN_VERIFIED_DATA_RULES = """
【行情硬数据与风险偏好纪律 — 必须遵守】
1. 辩论与投资决策中出现的**股价、市盈率、市净率、同业 PE 对比**只能引用下方「行情硬数据」块中的数字。
2. **禁止**用模型记忆、估算或未在硬数据块出现的口径填写 PE/PB。
3. **禁止**将净利润同比增速（如 +30.50%）当作市盈率（如 30 倍）；增速用 %，市盈率用 ×。
4. 若存在「投资者持仓」块，讨论盈亏、成本与加减仓须引用该块数字，**禁止**编造持仓成本 or 股数。
5. 【国家队/大基金高位减持红线】：若近期该股遭遇国家集成电路大基金（或其他同级国家队/行业龙头核心产业资本）公告减持，且该股 TTM PE > 40x，一律视为高位抱团瓦解风险，禁止建仓，评级强制压死在 Underweight 或 Sell。
6. 【季节性气候异常防御偏好】：若检测到当前处于 5 月 - 6 月（迎峰度夏前夕），且气象部门发布强拉尼娜/厄尔尼诺等温度异常预警，允许对电力（特别是火电/高分红公用事业）及煤炭开采等高股息防御性资产给予估值溢价，并支持作为大资金流切换的主攻对冲方向，评级可适度放宽至 Buy/Overweight。
7. 所有智能体（多空研究员、交易员、风险控制和投资组合经理）必须仔细阅读并执行下方「当前市场环境」所指导的交易偏好倾向及防爆红线。
"""


def append_verified_market_facts(base_prompt: str, state: dict) -> str:
    block = (state.get("verified_market_facts") or "").strip()
    if not block:
        return base_prompt

    # 动态检测当前题材环境
    ticker = state.get("company_of_interest") or ""
    trade_date = state.get("trade_date") or ""

    regime = detect_market_regime(ticker, trade_date)
    regime_instructions = get_regime_prompt_instructions(regime)

    # 将动态检测到的题材偏好与底线规则一并拼接注入
    return f"{base_prompt.rstrip()}\n\n{CN_VERIFIED_DATA_RULES}\n{regime_instructions}\n\n{block}\n"
