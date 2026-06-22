"""Tests for P0–P4 intelligence detail improvements."""

from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    ReflectionFailureMode,
    ReflectionOutcome,
    format_reflection_storage,
    render_pm_decision,
)
from tradingagents.agents.utils.past_context import format_past_context_for_role
from tradingagents.agents.utils.report_quality import (
    annotate_low_quality_report,
    assess_report,
    build_quality_gate_updates,
)
from tradingagents.dataflows.audit_pm_context import format_audit_kpi_mandate
from tradingagents.graph.analyst_quality_gate import analyst_quality_gate_node
from tradingagents.graph.debate_context import (
    arguments_too_similar,
    should_end_investment_debate,
)
from tradingagents.graph.propagation import Propagator


def test_assess_report_flags_short_and_empty():
    assert assess_report("")["level"] == "low"
    assert assess_report("x" * 50)["level"] == "low"
    ok = "结论偏多。[L2] PE 25× RSI 55 MACD 金叉 " + ("detail " * 40)
    assert assess_report(ok)["level"] == "ok"


def test_build_quality_gate_annotates_reports():
    state = {
        "market_report": "too short",
        "sentiment_report": "ok " * 80 + "[L2] 热度上升 12%",
        "news_report": "",
        "fundamentals_report": "fund " * 80 + "[L1] 营收 +10%",
        "verified_market_facts": "TTM PE：45.2×",
    }
    updates = build_quality_gate_updates(state)
    assert "report_quality_notes" in updates
    assert "低质量" in updates["report_quality_notes"]
    assert "⚠️" in updates["market_report"]


def test_analyst_quality_gate_node():
    out = analyst_quality_gate_node({"market_report": "tiny"})
    assert out.get("report_quality_notes")


def test_past_context_role_slicing():
    ctx = (
        "Past analyses of NVDA (most recent first):\n"
        "[2026-01-01 | NVDA | Buy | +5% | +2% | 5d]\n"
        "DECISION:\nBuy\n\n"
        "REFLECTION:\nFAILURE_MODE: timing\nToo early.\n\n"
        "Recent cross-ticker lessons:\n"
        "[2026-01-02 | AAPL | Hold | -1%]\n"
        "High PE trap."
    )
    bull = format_past_context_for_role(ctx, "bull_researcher")
    assert "NVDA" in bull
    pm = format_past_context_for_role(ctx, "portfolio_manager")
    assert pm == ctx


def test_debate_early_termination_on_repetition():
    repeated = "growth moat pricing power margin expansion catalyst sector rotation"
    state = {
        "investment_debate_state": {
            "history": f"Bull Analyst: {repeated}\n\nBear Analyst: {repeated}",
            "count": 2,
        }
    }
    assert should_end_investment_debate(state)
    assert arguments_too_similar(repeated, repeated)


def test_audit_kpi_mandate_empty_results(tmp_path):
    text = format_audit_kpi_mandate(tmp_path)
    assert "动态审计 KPI" in text
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="Wait.",
        investment_thesis="PE from verified block.",
        evidence_citations=["TTM PE 45× from verified facts", "Bear: high inventory"],
    )
    md = render_pm_decision(decision)
    assert "**Evidence Citations**:" in md
    assert "TTM PE 45×" in md


def test_reflection_storage_includes_failure_mode():
    stored = format_reflection_storage(
        ReflectionOutcome(
            failure_mode=ReflectionFailureMode.VALUATION,
            reflection="PE was too rich.",
        )
    )
    assert stored.startswith("FAILURE_MODE: valuation")


def test_propagator_initializes_new_state_fields():
    state = Propagator().create_initial_state("688981", "2026-06-22")
    assert state["report_quality_notes"] == ""
    assert state["investment_debate_state"]["summary"] == ""
    assert state["risk_debate_state"]["summary"] == ""


def test_audit_kpi_mandate_empty_results(tmp_path):
    text = format_audit_kpi_mandate(tmp_path)
    assert "动态审计 KPI" in text
