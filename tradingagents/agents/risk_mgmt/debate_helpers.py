"""Shared helpers for risk-management debators."""

from __future__ import annotations

from tradingagents.graph.debate_context import (
    format_risk_debate_history,
    maybe_refresh_risk_summary,
)


def safe_report(text: str) -> str:
    cleaned = (text or "").strip()
    return cleaned if cleaned else (
        "(This report was not generated or is unavailable for this run. "
        "Do NOT assume, fabricate, or speculate on any facts, metrics, "
        "or announcements from this category.)"
    )


def risk_reports_block(state: dict) -> str:
    return (
        f"Market Research Report: {safe_report(state.get('market_report'))}\n"
        f"Social Media Sentiment Report: {safe_report(state.get('sentiment_report'))}\n"
        f"Latest World Affairs Report: {safe_report(state.get('news_report'))}\n"
        f"Company Fundamentals Report: {safe_report(state.get('fundamentals_report'))}"
    )
