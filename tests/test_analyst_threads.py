import unittest

from langchain_core.messages import AIMessage, HumanMessage

from tradingagents.agents.utils.analyst_threads import (
    analyst_node_return,
    create_analyst_clear_node,
    extract_last_ai_content,
)


class AnalystThreadTests(unittest.TestCase):
    def test_analyst_node_return_skips_empty_report(self):
        msg = AIMessage(content="tool round", tool_calls=[{"id": "1", "name": "get_stock_data", "args": {}}])
        out = analyst_node_return(
            {"messages": []},
            thread_key=None,
            message=msg,
            report_key="market_report",
            report="",
        )
        self.assertNotIn("market_report", out)

        final = analyst_node_return(
            {"messages": []},
            thread_key=None,
            message=AIMessage(content="final market report"),
            report_key="market_report",
            report="final market report",
        )
        self.assertEqual(final["market_report"], "final market report")

    def test_clear_node_backfills_report_from_thread(self):
        state = {
            "market_report": "",
            "analyst_threads": {
                "market": [
                    HumanMessage(content="Continue"),
                    AIMessage(content="draft with tools", tool_calls=[{"id": "1", "name": "x", "args": {}}]),
                    AIMessage(content="## 技术面结论\n趋势向上"),
                ]
            },
        }
        clear = create_analyst_clear_node("market", "market_report")
        out = clear(state)
        self.assertIn("技术面结论", out.get("market_report", ""))

    def test_extract_last_ai_content_from_messages(self):
        state = {
            "messages": [
                HumanMessage(content="Continue"),
                AIMessage(content="news summary body"),
            ]
        }
        self.assertEqual(extract_last_ai_content(state, None), "news summary body")


if __name__ == "__main__":
    unittest.main()
