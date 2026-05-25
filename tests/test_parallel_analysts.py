import unittest

from langgraph.graph import START

from tradingagents.graph.analyst_join import ANALYST_JOIN_NODE
from tradingagents.graph.setup import GraphSetup
from tradingagents.graph.conditional_logic import ConditionalLogic


class ParallelAnalystGraphTests(unittest.TestCase):
    def _make_setup(self, concurrency: int) -> GraphSetup:
        return GraphSetup(
            quick_thinking_llm=None,
            deep_thinking_llm=None,
            tool_nodes={},
            conditional_logic=ConditionalLogic(),
            analyst_concurrency_limit=concurrency,
        )

    def test_parallel_wires_fan_out_and_join(self):
        setup = self._make_setup(4)
        # Tool nodes empty — only inspect graph structure via workflow
        from unittest.mock import MagicMock

        setup.tool_nodes = {
            "market": MagicMock(),
            "social": MagicMock(),
            "news": MagicMock(),
            "fundamentals": MagicMock(),
        }
        workflow = setup.setup_graph(
            ["market", "social", "news", "fundamentals"]
        )
        nodes = set(workflow.nodes.keys())
        self.assertIn(ANALYST_JOIN_NODE, nodes)

        # Compiled graph not required; check edges on builder
        edges_from_start = [
            e for e in workflow.edges if e[0] == START
        ]
        self.assertEqual(len(edges_from_start), 4)

    def test_sequential_single_edge_from_start(self):
        setup = self._make_setup(1)
        from unittest.mock import MagicMock

        setup.tool_nodes = {"market": MagicMock()}
        workflow = setup.setup_graph(["market"])
        edges_from_start = [e for e in workflow.edges if e[0] == START]
        self.assertEqual(len(edges_from_start), 1)
        self.assertNotIn(ANALYST_JOIN_NODE, workflow.nodes)
