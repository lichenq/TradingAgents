"""Parallel analyst message thread helpers."""

import unittest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from tradingagents.agents.utils.analyst_threads import (
    get_analyst_thread,
    last_message_in_thread,
    merge_analyst_threads,
    sanitize_messages_for_llm,
    tool_names_from_update,
)
from langchain_core.messages import HumanMessage, ToolMessage


class TestAnalystThreads(unittest.TestCase):
    def test_merge_threads(self):
        a = merge_analyst_threads({"market": [HumanMessage(content="a")]}, {"market": [AIMessage(content="b")]})
        self.assertEqual(len(a["market"]), 2)

    def test_seed_from_human(self):
        state = {"messages": [HumanMessage(content="688981.SS")]}
        thread = get_analyst_thread(state, "fundamentals")
        self.assertEqual(len(thread), 1)

    def test_last_message_prefers_thread(self):
        msg = AIMessage(content="x", tool_calls=[{"name": "get_fundamentals", "args": {}, "id": "1"}])
        state = {
            "messages": [HumanMessage(content="ticker")],
            "analyst_threads": {"fundamentals": [msg]},
        }
        last = last_message_in_thread(state, "fundamentals")
        self.assertTrue(last.tool_calls)

    def test_merge_reset_replaces_thread(self):
        old = {"market": [HumanMessage(content="a"), HumanMessage(content="b")]}
        new = {"market": [HumanMessage(content="Continue")]}
        merged = merge_analyst_threads(old, new)
        self.assertEqual(len(merged["market"]), 1)
        self.assertEqual(merged["market"][0].content, "Continue")

    def test_tool_names_from_threads(self):
        msg = MagicMock()
        msg.tool_calls = [{"name": "get_stock_data"}]
        names = tool_names_from_update({"analyst_threads": {"market": [msg]}})
        self.assertEqual(names, ["get_stock_data"])

    def test_sanitize_drops_orphan_tool_calls(self):
        ai = AIMessage(
            content="",
            tool_calls=[{"name": "get_fundamentals", "args": {}, "id": "tc1"}],
        )
        cleaned = sanitize_messages_for_llm([HumanMessage(content="002594.SZ"), ai])
        self.assertEqual(len(cleaned), 1)

    def test_sanitize_keeps_complete_tool_round(self):
        ai = AIMessage(
            content="",
            tool_calls=[{"name": "get_fundamentals", "args": {}, "id": "tc1"}],
        )
        tool = ToolMessage(content="ok", tool_call_id="tc1")
        cleaned = sanitize_messages_for_llm(
            [HumanMessage(content="002594.SZ"), ai, tool]
        )
        self.assertEqual(len(cleaned), 3)

    def test_parallel_last_message_uses_seed_not_global(self):
        ai = AIMessage(
            content="",
            tool_calls=[{"name": "get_news", "args": {}, "id": "x"}],
        )
        state = {
            "messages": [HumanMessage(content="002594.SZ"), ai],
            "analyst_threads": {"fundamentals": []},
        }
        last = last_message_in_thread(state, "fundamentals")
        self.assertEqual(last.content, "002594.SZ")


if __name__ == "__main__":
    unittest.main()
