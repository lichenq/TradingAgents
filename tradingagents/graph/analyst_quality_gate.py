"""Graph node: validate analyst reports before the investment debate."""

from __future__ import annotations

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.report_quality import build_quality_gate_updates

ANALYST_QUALITY_GATE_NODE = "Analyst Quality Gate"


def analyst_quality_gate_node(state: AgentState) -> dict:
    return build_quality_gate_updates(state)
