"""Shared analyst report section skeleton (lightweight structured output)."""

from __future__ import annotations

ANALYST_REPORT_SECTIONS = """
## 输出结构（必须包含以下 Markdown 小节）

1. **结论 (Direction)**：偏多 / 偏空 / 中性，一句话。
2. **关键证据 (Key Evidence)**：2–5 条，每条标注证据等级 [L1]–[L4] 并引用工具/预取数据。
3. **主要风险 (Risks)**：1–3 条。
4. **数据缺口 (Data Gaps)**：尚缺或不可信的数据；无则写「无显著缺口」。
5. 文末 **Markdown 表格** 汇总关键信号。
"""

EVIDENCE_TIER_RULES = """
## 证据分级（撰写报告时必须标注）

- [L1] 监管公告、财报、交易所披露
- [L2] 可验证物理/交易异动（招聘、招标、海关、量价）
- [L3] 权威媒体/券商研报
- [L4] 论坛传闻（仅作情绪参考，不得支撑核心因果链）
"""
