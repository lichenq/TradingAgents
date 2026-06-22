"""Debate history compression and early-termination helpers."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEBATE_HISTORY_CHAR_LIMIT = 4500
DEBATE_SUMMARY_CHAR_LIMIT = 900
_REPEAT_SIMILARITY_THRESHOLD = 0.72


def _normalize(text: str) -> set[str]:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower())
    return set(tokens)


def arguments_too_similar(a: str, b: str) -> bool:
    sa, sb = _normalize(a), _normalize(b)
    if len(sa) < 8 or len(sb) < 8:
        return False
    overlap = len(sa & sb) / max(len(sa | sb), 1)
    return overlap >= _REPEAT_SIMILARITY_THRESHOLD


def summarize_debate(llm: Any, history: str, *, topic: str) -> str:
    body = (history or "").strip()
    if len(body) <= DEBATE_HISTORY_CHAR_LIMIT:
        return body
    prompt = (
        f"Summarize this {topic} debate in ≤200 words. "
        "Keep only: open disagreements, cited L1/L2 facts, and unresolved risks. "
        "Plain prose, no bullets.\n\n"
        f"{body[-8000:]}"
    )
    try:
        summary = llm.invoke(prompt).content.strip()
        if len(summary) > DEBATE_SUMMARY_CHAR_LIMIT:
            summary = summary[:DEBATE_SUMMARY_CHAR_LIMIT] + "..."
        return summary
    except Exception as exc:
        logger.warning("Debate summarization failed: %s", exc)
        return body[-DEBATE_HISTORY_CHAR_LIMIT:]


def format_investment_debate_history(state: dict, llm: Optional[Any] = None) -> str:
    debate = state.get("investment_debate_state") or {}
    summary = (debate.get("summary") or "").strip()
    history = (debate.get("history") or "").strip()
    if not history:
        return summary
    if len(history) <= DEBATE_HISTORY_CHAR_LIMIT:
        if summary:
            return f"Prior rounds (summary):\n{summary}\n\nLatest exchange:\n{history}"
        return history
    if llm is not None and not summary:
        summary = summarize_debate(llm, history, topic="bull/bear investment")
    recent = history[-2500:]
    parts = []
    if summary:
        parts.append(f"Prior rounds (summary):\n{summary}")
    parts.append(f"Latest exchange:\n{recent}")
    return "\n\n".join(parts)


def format_risk_debate_history(state: dict, llm: Optional[Any] = None) -> str:
    debate = state.get("risk_debate_state") or {}
    summary = (debate.get("summary") or "").strip()
    history = (debate.get("history") or "").strip()
    if not history:
        return summary
    if len(history) <= DEBATE_HISTORY_CHAR_LIMIT:
        if summary:
            return f"Prior rounds (summary):\n{summary}\n\nLatest exchange:\n{history}"
        return history
    if llm is not None and not summary:
        summary = summarize_debate(llm, history, topic="risk-management")
    recent = history[-2500:]
    parts = []
    if summary:
        parts.append(f"Prior rounds (summary):\n{summary}")
    parts.append(f"Latest exchange:\n{recent}")
    return "\n\n".join(parts)


def should_end_investment_debate(state: dict) -> bool:
    debate = state.get("investment_debate_state") or {}
    history = (debate.get("history") or "").strip()
    if not history:
        return False
    chunks = [c.strip() for c in history.split("\n\n") if c.strip()]
    if len(chunks) < 2:
        return False
    return arguments_too_similar(chunks[-1], chunks[-2])


def maybe_refresh_investment_summary(state: dict, llm: Any) -> str:
    debate = state.get("investment_debate_state") or {}
    history = (debate.get("history") or "").strip()
    if len(history) <= DEBATE_HISTORY_CHAR_LIMIT:
        return debate.get("summary") or ""
    return summarize_debate(llm, history, topic="bull/bear investment")


def maybe_refresh_risk_summary(state: dict, llm: Any) -> str:
    debate = state.get("risk_debate_state") or {}
    history = (debate.get("history") or "").strip()
    if len(history) <= DEBATE_HISTORY_CHAR_LIMIT:
        return debate.get("summary") or ""
    return summarize_debate(llm, history, topic="risk-management")
