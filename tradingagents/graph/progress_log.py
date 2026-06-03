"""Human-readable progress logging for programmatic graph runs (propagate)."""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Literal, Optional, TextIO, Tuple

ActivityKind = Literal["llm", "data"]

# LangGraph node name → display label (Chinese; matches CLI agent names where possible)
NODE_LABELS: Dict[str, str] = {
    "Market Analyst": "市场分析",
    "Msg Clear Market": "市场分析 · 整理上下文",
    "tools_market": "市场分析 · 数据工具",
    "Sentiment Analyst": "情绪/舆情分析",
    "Msg Clear Sentiment": "情绪分析 · 整理上下文",
    "tools_social": "情绪分析 · 数据工具",
    "News Analyst": "新闻分析",
    "Msg Clear News": "新闻分析 · 整理上下文",
    "tools_news": "新闻分析 · 数据工具",
    "Fundamentals Analyst": "基本面分析",
    "Msg Clear Fundamentals": "基本面分析 · 整理上下文",
    "tools_fundamentals": "基本面分析 · 数据工具",
    "Bull Researcher": "多头研究员",
    "Bear Researcher": "空头研究员",
    "Research Manager": "研究经理",
    "Trader": "交易员",
    "Aggressive Analyst": "激进风控",
    "Neutral Analyst": "中性风控",
    "Conservative Analyst": "保守风控",
    "Portfolio Manager": "投资组合经理",
    "Analyst Team Join": "分析师汇合",
}

# Nodes that invoke data vendors / subprocesses (not LLM inference).
_DATA_TOOL_NODES = frozenset(
    name for name in NODE_LABELS if name.startswith("tools_")
)

_STALL_HINTS: Dict[ActivityKind, str] = {
    "llm": "等待 LLM 响应",
    "data": "正在拉取 A 股数据",
}

REPORT_LABELS: Dict[str, str] = {
    "market_report": "市场报告",
    "sentiment_report": "情绪报告",
    "news_report": "新闻报告",
    "fundamentals_report": "基本面报告",
    "investment_plan": "多空辩论结论",
    "trader_investment_plan": "交易员计划",
    "final_trade_decision": "最终交易决策",
}


def progress_logging_enabled(config: Optional[Dict[str, Any]] = None) -> bool:
    """True unless config or TRADINGAGENTS_PROGRESS_LOG disables it."""
    if config is not None and config.get("progress_logging") is False:
        return False
    import os

    raw = os.environ.get("TRADINGAGENTS_PROGRESS_LOG", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    if config is not None and config.get("progress_logging") is True:
        return True
    # Default on for programmatic runs (propagate without CLI Rich UI).
    return config is None or config.get("progress_logging", True)


def label_node(node_name: str) -> str:
    return NODE_LABELS.get(node_name, node_name)


def classify_activity(
    node_name: str, update: Optional[Dict[str, Any]] = None
) -> ActivityKind:
    """Classify stall reason: LLM inference vs data fetch / tool execution."""
    if node_name in _DATA_TOOL_NODES or node_name.startswith("tools_"):
        return "data"
    if extract_tool_names(update):
        return "data"
    return "llm"


def extract_tool_names(update: Optional[Dict[str, Any]]) -> List[str]:
    from tradingagents.agents.utils.analyst_threads import tool_names_from_update

    return tool_names_from_update(update)


class GraphProgressLogger:
    """Stream the graph with periodic heartbeat lines so long LLM/data waits are visible."""

    HEARTBEAT_SEC = 30

    def __init__(
        self,
        ticker: str,
        trade_date: str,
        *,
        stream: Optional[TextIO] = None,
        heartbeat_sec: int = 30,
    ):
        self.ticker = ticker
        self.trade_date = trade_date
        self.stream = stream or sys.stderr
        self.heartbeat_sec = heartbeat_sec
        self._t0 = time.monotonic()
        self._last_event = self._t0
        self._current_phase = "初始化"
        self._activity_kind: ActivityKind = "llm"
        self._completed_reports: set[str] = set()
        self._prev_values: Dict[str, Any] = {}
        self._stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._seen_nodes: set[str] = set()

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _elapsed(self) -> float:
        return time.monotonic() - self._t0

    def _gap(self) -> float:
        return time.monotonic() - self._last_event

    def set_activity_kind(self, kind: ActivityKind) -> None:
        if kind in _STALL_HINTS:
            self._activity_kind = kind

    def _stall_hint(self) -> str:
        return _STALL_HINTS[self._activity_kind]

    def _log(self, msg: str) -> None:
        gap = self._gap()
        gap_hint = f" +{gap:.0f}s" if gap >= 5 else ""
        line = f"[{self._ts()}]{gap_hint} {msg}\n"
        self.stream.write(line)
        self.stream.flush()
        self._last_event = time.monotonic()

    def _start_heartbeat(self) -> None:
        def loop() -> None:
            while not self._stop.wait(self.heartbeat_sec):
                idle = time.monotonic() - self._last_event
                if idle >= self.heartbeat_sec:
                    self._log(
                        f"⏳ 仍在运行: {self._current_phase} "
                        f"(已 {idle:.0f}s 无新步骤；{self._stall_hint()}，并未卡死)"
                    )

        self._heartbeat_thread = threading.Thread(
            target=loop, name="tradingagents-progress-heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=2)

    def log_start(self, extra_lines: Optional[Iterable[str]] = None) -> None:
        self._log(f"▶ 开始分析 {self.ticker} · 交易日 {self.trade_date}")
        if extra_lines:
            for line in extra_lines:
                self._log(f"  · {line}")

    def _on_node_update(self, node_name: str, update: Optional[Dict[str, Any]]) -> None:
        if not update:
            return
        label = label_node(node_name)
        self._current_phase = label
        self._activity_kind = classify_activity(node_name, update)
        tools = extract_tool_names(update)
        if tools:
            self._log(f"▶ {label} · 调用工具: {', '.join(tools)}")
        elif node_name not in self._seen_nodes:
            self._seen_nodes.add(node_name)
            self._log(f"▶ {label}")

    def _on_values(self, state: Dict[str, Any]) -> None:
        for key, title in REPORT_LABELS.items():
            new_val = state.get(key) or ""
            old_val = self._prev_values.get(key) or ""
            if new_val and new_val != old_val and key not in self._completed_reports:
                self._completed_reports.add(key)
                self._log(f"✓ {title} 已生成 ({len(str(new_val))} 字)")

        inv = state.get("investment_debate_state") or {}
        if isinstance(inv, dict):
            count = inv.get("count") or 0
            prev_inv = self._prev_values.get("investment_debate_state") or {}
            prev_count = prev_inv.get("count", 0) if isinstance(prev_inv, dict) else 0
            if count > prev_count:
                self._current_phase = "多空辩论"
                self._activity_kind = "llm"
                self._log(f"▶ 投资辩论 · 第 {count} 轮")

        risk = state.get("risk_debate_state") or {}
        if isinstance(risk, dict):
            count = risk.get("count") or 0
            prev_risk = self._prev_values.get("risk_debate_state") or {}
            prev_count = prev_risk.get("count", 0) if isinstance(prev_risk, dict) else 0
            if count > prev_count:
                self._current_phase = "风控辩论"
                self._activity_kind = "llm"
                self._log(f"▶ 风控辩论 · 第 {count} 轮")

        self._prev_values = {
            k: state.get(k)
            for k in list(REPORT_LABELS)
            + ["investment_debate_state", "risk_debate_state"]
        }

    def log_finish(self, decision: str, *, md_report_path: str | None = None) -> None:
        preview = (decision or "").strip().replace("\n", " ")[:120]
        self._log(
            f"✓ 全流程完成 · 总耗时 {self._elapsed():.0f}s"
            + (f" · 决策摘要: {preview}" if preview else "")
        )
        if md_report_path:
            self._log(f"📄 Markdown 报告: {md_report_path}")

    def run_stream(self, graph: Any, init_state: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
        """Stream graph with updates+values; return final merged state."""
        self._start_heartbeat()
        stream_args = dict(args)
        stream_args["stream_mode"] = ["updates", "values"]

        final_state: Dict[str, Any] = {}
        try:
            for mode, chunk in graph.stream(init_state, **stream_args):
                if mode == "updates":
                    if not chunk:
                        continue
                    for node_name, update in chunk.items():
                        if update is None:
                            continue
                        self._on_node_update(node_name, update)
                else:
                    final_state = chunk
                    self._on_values(chunk)
        finally:
            self._stop_heartbeat()

        if not final_state:
            raise RuntimeError("Graph stream produced no final state")
        return final_state
