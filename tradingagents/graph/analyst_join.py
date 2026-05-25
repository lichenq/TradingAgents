"""Barrier node after parallel analyst branches complete."""

from __future__ import annotations

from tradingagents.agents.utils.agent_states import AgentState

ANALYST_JOIN_NODE = "Analyst Team Join"


def analysts_join_node(state: AgentState) -> dict:
    """Fan-in pass-through once every selected analyst has finished."""
    return {}
