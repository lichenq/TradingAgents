"""Inject pre-fetched market hard data into debate / decision prompts."""

from __future__ import annotations

CN_VERIFIED_DATA_RULES = """
【行情硬数据纪律 — 必须遵守】
1. 辩论与投资决策中出现的**股价、市盈率、市净率、同业 PE 对比**只能引用下方「行情硬数据」块中的数字。
2. **禁止**用模型记忆、估算或未在硬数据块出现的口径填写 PE/PB。
3. **禁止**将净利润同比增速（如 +30.50%）当作市盈率（如 30 倍）；增速用 %，市盈率用 ×。
4. 若硬数据块未提供某指标，须写明「未预取，不作数值判断」，不得猜测。
5. 若存在「投资者持仓」块，讨论盈亏、成本与加减仓须引用该块数字，**禁止**编造持仓成本或股数。
"""


def append_verified_market_facts(base_prompt: str, state: dict) -> str:
    block = (state.get("verified_market_facts") or "").strip()
    if not block:
        return base_prompt
    return f"{base_prompt.rstrip()}\n\n{CN_VERIFIED_DATA_RULES}\n\n{block}\n"
