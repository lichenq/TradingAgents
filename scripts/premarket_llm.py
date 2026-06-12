#!/usr/bin/env python3
"""LLM layer for premarket sector rotation (news insight + brief)."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.sector_mapping import all_canonical_names

MAX_NEWS_FOR_LLM = int(os.environ.get("PREMARKET_LLM_NEWS", "20"))
MAX_SECTORS = int(os.environ.get("PREMARKET_LLM_SECTORS", "3"))


def is_enabled() -> bool:
    flag = os.environ.get("PREMARKET_LLM", "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    return True


def llm_on_open() -> bool:
    """Open confirm (9:35) skips LLM by default; reuse previous snapshot."""
    return os.environ.get("PREMARKET_LLM_OPEN", "0").strip().lower() in ("1", "true", "yes", "on")


def should_run_llm(*, previous_snapshot: dict[str, Any] | None) -> bool:
    if not is_enabled():
        return False
    if previous_snapshot is not None and not llm_on_open():
        return False
    return True


def reuse_insight_from_previous(
    result: dict[str, Any],
    previous: dict[str, Any],
    news_layer: dict[str, Any],
) -> None:
    prev_insight = previous.get("llm_insight") or {}
    if prev_insight.get("ok"):
        copied = dict(prev_insight)
        copied["reused_from"] = "previous_snapshot"
        result["llm_insight"] = copied
        result["news_catalyst"] = enrich_news_catalyst(news_layer, copied)
    prev_deep = previous.get("deep_curation") or {}
    if prev_deep.get("ok"):
        result["deep_curation"] = {**prev_deep, "reused_from": "previous_snapshot"}


def _extract_json(text: str) -> dict[str, Any]:
    body = (text or "").strip()
    if body.startswith("```"):
        body = re.sub(r"^```(?:json)?\s*", "", body)
        body = re.sub(r"\s*```$", "", body)
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM response has no JSON object")
    return json.loads(body[start : end + 1])


def _valid_sectors(raw: list[Any]) -> list[dict[str, Any]]:
    allowed = set(all_canonical_names())
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ind = (item.get("industry") or "").strip()
        if ind not in allowed:
            continue
        reason = _clip(str(item.get("reason") or ""), 40)
        conf = item.get("confidence") or "medium"
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        out.append({"industry": ind, "reason": reason, "confidence": conf})
        if len(out) >= MAX_SECTORS:
            break
    return out


def _clip(text: str, n: int) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _headline(item: dict[str, Any]) -> str:
    title = (item.get("title") or "").strip()
    if title:
        return title
    content = (item.get("content") or "").strip()
    content = re.sub(r"^【.*?】", "", content).strip()
    return _clip(content, 48)


def _compact_summary(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    mc = summary.get("market_limit_up_count")
    if mc is not None:
        lines.append(f"涨停 {mc} 家")
    for s in summary.get("top_sectors_by_fund_flow", [])[:3]:
        leaders = "、".join(x.get("name", "") for x in s.get("limit_up_leaders", [])[:2])
        lines.append(
            f"#{s.get('rank')} {s.get('industry')} 流入{s.get('main_net_inflow_yi')}亿 "
            f"{s.get('change_pct')}% 涨停:{leaders or '-'}"
        )
    cat = summary.get("news_catalyst") or {}
    kw = "、".join(p.get("industry", "") for p in cat.get("predicted_sectors", [])[:5])
    if kw:
        lines.append(f"关键词新闻命中: {kw}")
    ahead = cat.get("ahead_of_fund_flow") or []
    if ahead:
        lines.append(f"新闻热但资金未确认: {'/'.join(ahead[:4])}")
    delta = summary.get("delta_vs_previous") or {}
    if delta.get("narrative"):
        lines.append(f"轮动: {delta['narrative']}")
    return "\n".join(lines)


def _build_prompt(summary: dict[str, Any], news_items: list[dict[str, Any]]) -> str:
    canon = "、".join(sorted(all_canonical_names()))
    headlines = "\n".join(f"{i + 1}. {_headline(it)}" for i, it in enumerate(news_items[:MAX_NEWS_FOR_LLM]))
    return f"""你是A股盘前板块轮动分析师。根据下方数据，输出严格 JSON（不要 markdown 代码块）：

{{
  "brief": "2句话总结，每句≤35字，面向次日盘前决策",
  "predicted_sectors": [
    {{"industry": "候选板块名", "reason": "≤30字因果", "confidence": "high|medium|low"}}
  ],
  "watch": "一句明日观察要点，≤35字"
}}

要求：
- predicted_sectors 最多 {MAX_SECTORS} 个
- industry 必须来自候选板块列表，不得自造
- 优先指出「新闻催化但资金流尚未确认」的方向
- 禁止编造未提供的价格、个股、政策细节

候选板块：{canon}

盘面快照：
{_compact_summary(summary)}

新闻标题：
{headlines or "（无）"}
"""


def _get_llm():
    from tradingagents.llm_clients import create_llm_client

    cfg = get_config()
    provider = cfg.get("llm_provider") or "openai"
    model = os.environ.get("PREMARKET_LLM_MODEL") or cfg.get("quick_think_llm") or "gpt-4o-mini"
    base_url = cfg.get("backend_url")
    client = create_llm_client(provider, model, base_url)
    return client.get_llm(), model


def build_insight(summary: dict[str, Any], news_items: list[dict[str, Any]]) -> dict[str, Any]:
    if not is_enabled():
        return {"ok": False, "enabled": False, "skipped": True}

    t0 = time.time()
    try:
        llm, model = _get_llm()
        prompt = _build_prompt(summary, news_items)
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        parsed = _extract_json(str(raw))
        sectors = _valid_sectors(parsed.get("predicted_sectors") or [])
        brief = _clip(str(parsed.get("brief") or ""), 120)
        watch = _clip(str(parsed.get("watch") or ""), 50)
        if not brief and not sectors:
            return {
                "ok": False,
                "enabled": True,
                "error": "empty LLM output",
                "model": model,
                "elapsed_ms": int((time.time() - t0) * 1000),
            }
        return {
            "ok": True,
            "enabled": True,
            "brief": brief,
            "watch": watch,
            "predicted_sectors": sectors,
            "model": model,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
    except Exception as exc:
        return {
            "ok": False,
            "enabled": True,
            "error": str(exc)[:200],
            "elapsed_ms": int((time.time() - t0) * 1000),
        }


def enrich_news_catalyst(catalyst: dict[str, Any], insight: dict[str, Any]) -> dict[str, Any]:
    """Attach LLM sectors to news_catalyst without dropping keyword hits."""
    if not insight.get("ok"):
        return catalyst
    llm_secs = insight.get("predicted_sectors") or []
    if not llm_secs:
        return catalyst
    catalyst = dict(catalyst)
    catalyst["llm_predicted"] = llm_secs
    if insight.get("watch"):
        catalyst["llm_watch"] = insight["watch"]
    return catalyst
