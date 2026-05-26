"""Export analysis state to markdown files (same layout as CLI save_report_to_disk)."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict


def save_analysis_report_md(
    final_state: Dict[str, Any],
    ticker: str,
    save_path: Path,
    *,
    trade_date: str = "",
    stock_name: str = "",
) -> Path:
    """Write per-section .md files and a consolidated complete_report.md."""
    save_path.mkdir(parents=True, exist_ok=True)
    sections = []

    from tradingagents.dataflows.report_paths import (
        build_report_bundle_name,
        report_code_for_ticker,
    )

    code = report_code_for_ticker(ticker)
    name = (stock_name or "").strip() or code
    bundle_label = build_report_bundle_name(ticker, trade_date or final_state.get("trade_date") or "")

    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    for key, fname, title in (
        ("market_report", "market.md", "Market Analyst"),
        ("sentiment_report", "sentiment.md", "Sentiment Analyst"),
        ("news_report", "news.md", "News Analyst"),
        ("fundamentals_report", "fundamentals.md", "Fundamentals Analyst"),
    ):
        text = final_state.get(key) or ""
        if not text:
            continue
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / fname).write_text(text, encoding="utf-8")
        analyst_parts.append((title, text))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        debate = final_state["investment_debate_state"]
        research_parts = []
        for key, fname, title in (
            ("bull_history", "bull.md", "Bull Researcher"),
            ("bear_history", "bear.md", "Bear Researcher"),
            ("judge_decision", "manager.md", "Research Manager"),
        ):
            text = debate.get(key) or ""
            if not text:
                continue
            research_dir.mkdir(exist_ok=True)
            (research_dir / fname).write_text(text, encoding="utf-8")
            research_parts.append((title, text))
        if research_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
            sections.append(f"## II. Research Team Decision\n\n{content}")

    verified = (final_state.get("verified_market_facts") or "").strip()
    if verified:
        (save_path / "verified_market_facts.md").write_text(verified, encoding="utf-8")
        sections.append(f"## I-b. Verified Market Facts (pre-debate)\n\n{verified}")

    plan = final_state.get("investment_plan") or ""
    if plan:
        (save_path / "investment_plan.md").write_text(plan, encoding="utf-8")
        sections.append(f"## II-b. Investment Plan\n\n{plan}")

    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        text = final_state["trader_investment_plan"]
        (trading_dir / "trader.md").write_text(text, encoding="utf-8")
        sections.append(f"## III. Trading Team Plan\n\n### Trader\n{text}")

    if final_state.get("risk_debate_state"):
        risk_dir = save_path / "4_risk"
        risk = final_state["risk_debate_state"]
        risk_parts = []
        for key, fname, title in (
            ("aggressive_history", "aggressive.md", "Aggressive Analyst"),
            ("conservative_history", "conservative.md", "Conservative Analyst"),
            ("neutral_history", "neutral.md", "Neutral Analyst"),
        ):
            text = risk.get(key) or ""
            if not text:
                continue
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / fname).write_text(text, encoding="utf-8")
            risk_parts.append((title, text))
        if risk_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
            sections.append(f"## IV. Risk Management Team Decision\n\n{content}")

        judge = risk.get("judge_decision") or ""
        if judge:
            portfolio_dir = save_path / "5_portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            (portfolio_dir / "decision.md").write_text(judge, encoding="utf-8")
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{judge}")

    final_decision = final_state.get("final_trade_decision") or ""
    if final_decision:
        (save_path / "final_trade_decision.md").write_text(final_decision, encoding="utf-8")
        sections.append(f"## VI. Final Trade Decision\n\n{final_decision}")

    trade_date = trade_date or final_state.get("trade_date") or ""
    header = (
        f"# {name}（{code}）交易分析报告\n\n"
        f"标的: {ticker}\n\n"
        f"交易日: {trade_date}\n\n"
        f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    complete = save_path / f"{bundle_label}.md"
    complete.write_text(header + "\n\n".join(sections), encoding="utf-8")
    # Stable alias for scripts / IDE bookmarks
    alias = save_path / "complete_report.md"
    if alias != complete:
        alias.write_text(complete.read_text(encoding="utf-8"), encoding="utf-8")
    return complete
