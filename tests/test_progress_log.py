import os
from unittest.mock import MagicMock

from tradingagents.graph.progress_log import (
    GraphProgressLogger,
    extract_tool_names,
    label_node,
    progress_logging_enabled,
)


class TestProgressLogHelpers:
    def test_label_node_known(self):
        assert label_node("Market Analyst") == "市场分析"
        assert label_node("tools_news") == "新闻分析 · 数据工具"

    def test_label_node_unknown_passthrough(self):
        assert label_node("Custom Node") == "Custom Node"

    def test_extract_tool_names_from_dict_calls(self):
        msg = MagicMock()
        msg.tool_calls = [{"name": "get_stock_data"}, {"name": "get_indicators"}]
        update = {"messages": [msg]}
        assert extract_tool_names(update) == ["get_stock_data", "get_indicators"]

    def test_progress_logging_enabled_default(self):
        assert progress_logging_enabled({"progress_logging": True}) is True
        assert progress_logging_enabled({"progress_logging": False}) is False

    def test_progress_logging_env_off(self, monkeypatch):
        monkeypatch.setenv("TRADINGAGENTS_PROGRESS_LOG", "0")
        assert progress_logging_enabled({"progress_logging": True}) is False

    def test_progress_logging_env_on(self, monkeypatch):
        monkeypatch.delenv("TRADINGAGENTS_PROGRESS_LOG", raising=False)
        monkeypatch.setenv("TRADINGAGENTS_PROGRESS_LOG", "1")
        assert progress_logging_enabled({}) is True


class TestGraphProgressLogger:
    def test_log_start_writes_to_stream(self):
        import io

        buf = io.StringIO()
        logger = GraphProgressLogger("600584.SS", "2026-05-23", stream=buf)
        logger.log_start(["行业新闻 +4"])
        out = buf.getvalue()
        assert "600584.SS" in out
        assert "行业新闻" in out
        assert "▶" in out

    def test_on_values_detects_report(self):
        import io

        buf = io.StringIO()
        logger = GraphProgressLogger("X", "2026-01-01", stream=buf, heartbeat_sec=999)
        logger._on_values({"market_report": "hello"})
        assert "市场报告" in buf.getvalue()
