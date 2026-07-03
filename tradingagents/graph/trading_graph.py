# TradingAgents/graph/trading_graph.py

import logging
import os
from pathlib import Path
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, List, Optional

import yfinance as yf

logger = logging.getLogger(__name__)

from langgraph.prebuilt import ToolNode

from tradingagents.llm_clients import create_llm_client

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.dataflows.report_paths import (
    build_report_bundle_name,
    report_bundle_dir,
    resolve_stock_display_name,
)
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.sector_queries import apply_ticker_news_queries

# Import the new abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_insider_transactions,
    get_global_news
)

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor
from .progress_log import GraphProgressLogger, progress_logging_enabled
from .report_export import save_analysis_report_md, sync_analysis_report_sqlite


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=["market", "social", "news", "fundamentals"],
        debug=False,
        config: Dict[str, Any] = None,
        callbacks: Optional[List] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()
        
        self.memory_log = TradingMemoryLog(self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
            analyst_concurrency_limit=self.config.get("analyst_concurrency_limit", 1),
        )

        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100),
        )
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        self.workflow = self.graph_setup.setup_graph(selected_analysts)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        return kwargs

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                ]
            ),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                ]
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_transactions,
                ]
            ),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                ]
            ),
        }

    def _resolve_benchmark(self, ticker: str) -> str:
        """Pick the benchmark ticker for alpha calculation against ``ticker``.

        ``config["benchmark_ticker"]`` overrides everything when set; otherwise
        the suffix map matches the ticker's exchange suffix (e.g. ``.T`` for
        Tokyo). US-listed tickers without a dotted suffix fall through to the
        empty-suffix entry (SPY by default). Unrecognised suffixes (including
        US tickers with dots like ``BRK.B``) also fall back to the empty-suffix
        entry, which is the right default because the alpha calculation works
        in USD.
        """
        explicit = self.config.get("benchmark_ticker")
        if explicit:
            return explicit
        benchmark_map = self.config.get("benchmark_map", {})
        ticker_upper = ticker.upper()
        for suffix, benchmark in benchmark_map.items():
            if suffix and ticker_upper.endswith(suffix.upper()):
                return benchmark
        return benchmark_map.get("", "SPY")

    def _fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5,
        benchmark: str = "SPY",
    ) -> Tuple[Optional[float], Optional[float], Optional[int]]:
        """Fetch raw and alpha return for ticker over holding_days from trade_date.

        ``benchmark`` is the index used as the alpha baseline (resolved by the
        caller via ``_resolve_benchmark``). Returns ``(raw_return, alpha_return,
        actual_holding_days)`` or ``(None, None, None)`` if price data is
        unavailable (too recent, delisted, or network error).
        """
        try:
            from tradingagents.market import cn_uses_a_share_skill
            from tradingagents.dataflows.a_share_returns import fetch_raw_and_alpha_returns

            if cn_uses_a_share_skill(ticker, self.config):
                return fetch_raw_and_alpha_returns(
                    ticker, benchmark, trade_date, holding_days
                )

            start = datetime.strptime(trade_date, "%Y-%m-%d")
            end = start + timedelta(days=holding_days + 7)  # buffer for weekends/holidays
            end_str = end.strftime("%Y-%m-%d")

            stock = yf.Ticker(ticker).history(start=trade_date, end=end_str)
            bench = yf.Ticker(benchmark).history(start=trade_date, end=end_str)

            if len(stock) < 2 or len(bench) < 2:
                return None, None, None

            actual_days = min(holding_days, len(stock) - 1, len(bench) - 1)
            raw = float(
                (stock["Close"].iloc[actual_days] - stock["Close"].iloc[0])
                / stock["Close"].iloc[0]
            )
            bench_ret = float(
                (bench["Close"].iloc[actual_days] - bench["Close"].iloc[0])
                / bench["Close"].iloc[0]
            )
            alpha = raw - bench_ret
            return raw, alpha, actual_days
        except Exception as e:
            logger.warning(
                "Could not resolve outcome for %s on %s vs %s (will retry next run): %s",
                ticker, trade_date, benchmark, e,
            )
            return None, None, None

    def _resolve_pending_entries(self, ticker: str) -> None:
        """Resolve pending log entries whose outcome data is available."""
        pending = self.memory_log.get_pending_entries()
        max_resolve = int(self.config.get("max_pending_resolve_per_run", 2))
        if max_resolve <= 0:
            return
        if len(pending) > max_resolve:
            logger.info(
                "Skipping %d pending memory-log entries (cap=%d); will retry next run",
                len(pending) - max_resolve,
                max_resolve,
            )
            pending = pending[:max_resolve]
        if not pending:
            return

        updates = []
        for entry in pending:
            entry_ticker = entry["ticker"]
            benchmark = self._resolve_benchmark(entry_ticker)
            raw, alpha, days = self._fetch_returns(
                entry_ticker, entry["date"], benchmark=benchmark,
            )
            if raw is None:
                continue
            reflection = self.reflector.reflect_on_final_decision(
                final_decision=entry.get("decision", ""),
                raw_return=raw,
                alpha_return=alpha,
                benchmark_name=benchmark,
            )
            updates.append({
                "ticker": entry_ticker,
                "trade_date": entry["date"],
                "raw_return": raw,
                "alpha_return": alpha,
                "holding_days": days,
                "reflection": reflection,
            })

        if updates:
            self.memory_log.batch_update_with_outcomes(updates)

    def propagate(self, company_name, trade_date=None, asset_type: str = "stock"):
        """Run the trading agents graph for a company on a specific date.

        ``asset_type`` selects between the stock pipeline (default) and the
        crypto pipeline (``"crypto"``) shipped in #567 — the CLI auto-detects
        from the ticker; programmatic callers pass it explicitly. When
        ``checkpoint_enabled`` is set in config, the graph is recompiled with
        a per-ticker SqliteSaver so a crashed run can resume from the last
        successful node on a subsequent invocation with the same ticker+date.

        When ``trade_date`` is omitted, uses today if it is a trading session
        for the ticker's market, otherwise the previous trading day.
        """
        if not trade_date:
            from tradingagents.dataflows.trade_date import resolve_default_trade_date

            trade_date = resolve_default_trade_date(company_name, self.config)
            logger.info("Resolved default trade_date=%s for %s", trade_date, company_name)

        self.ticker = company_name

        progress_logger = None
        if progress_logging_enabled(self.config):
            progress_logger = GraphProgressLogger(company_name, str(trade_date))
            progress_logger.log_start()

        pending = self.memory_log.get_pending_entries()
        max_resolve = int(self.config.get("max_pending_resolve_per_run", 2))
        if pending and progress_logger and max_resolve > 0:
            n = min(len(pending), max_resolve)
            skipped = len(pending) - n
            msg = f"回放 {n} 条历史 pending 决策（LLM 复盘）"
            if skipped:
                msg += f"，跳过 {skipped} 条"
            progress_logger.log_phase(msg)

        # Resolve pending memory-log entries before the pipeline runs.
        self._resolve_pending_entries(company_name)

        # Recompile with a checkpointer if the user opted in.
        if self.config.get("checkpoint_enabled"):
            self._checkpointer_ctx = get_checkpointer(
                self.config["data_cache_dir"], company_name
            )
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

            step = checkpoint_step(
                self.config["data_cache_dir"], company_name, str(trade_date)
            )
            if step is not None:
                logger.info(
                    "Resuming from step %d for %s on %s", step, company_name, trade_date
                )
            else:
                logger.info("Starting fresh for %s on %s", company_name, trade_date)

        try:
            return self._run_graph(
                company_name,
                trade_date,
                asset_type=asset_type,
                progress_logger=progress_logger,
            )
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()

    def _run_graph(
        self,
        company_name,
        trade_date,
        asset_type: str = "stock",
        progress_logger: Optional[GraphProgressLogger] = None,
    ):
        """Execute the graph and write the resulting state to disk and memory log."""
        self.config = apply_ticker_news_queries(company_name, self.config)
        set_config(self.config)
        extra = self.config.get("ticker_news_queries") or []
        if extra:
            logger.info(
                "Appended %d ticker industry news queries for %s: %s",
                len(extra),
                company_name,
                extra,
            )

        progress_extra = []
        if extra:
            progress_extra.append(
                f"行业新闻查询 +{len(extra)}: {', '.join(str(q)[:40] for q in extra[:3])}"
                + (" …" if len(extra) > 3 else "")
            )

        from tradingagents.dataflows.cn_prefetch import run_cn_prefetch, get_prefetched_json
        from tradingagents.market import cn_uses_a_share_skill, normalize_a_share_code

        verified_market_facts = ""
        scheduled_event_alerts: List[Dict[str, Any]] = []
        if cn_uses_a_share_skill(company_name, self.config):
            workers = max(1, int(self.config.get("analyst_concurrency_limit", 4)))
            if progress_logger:
                progress_logger.log_phase(
                    f"并行预取 A 股数据（{workers} 路，约 1 分钟）"
                )
                progress_logger.set_activity_kind("data")
            prefetch_lines = run_cn_prefetch(
                company_name,
                str(trade_date),
                self.config,
                max_workers=workers,
            )
            from tradingagents.dataflows.cn_technical import require_cn_technical_ready
            from tradingagents.dataflows.cn_valuation import require_cn_valuation_ready
            from tradingagents.dataflows.scheduled_events import (
                build_scheduled_alerts,
                enrich_verified_with_scheduled_events,
            )

            verified_market_facts = require_cn_valuation_ready(company_name, self.config)
            require_cn_technical_ready(company_name)
            from tradingagents.dataflows.limit_entry_rules import enrich_verified_with_entry_levels

            verified_market_facts = enrich_verified_with_entry_levels(
                verified_market_facts,
                company_name,
                str(trade_date),
            )
            code6 = normalize_a_share_code(company_name)
            events_payload = get_prefetched_json(f"events_raw:{code6}")
            scheduled_event_alerts = build_scheduled_alerts(events_payload, str(trade_date))
            verified_market_facts = enrich_verified_with_scheduled_events(
                verified_market_facts,
                scheduled_event_alerts,
            )
            if scheduled_event_alerts and progress_logger:
                top = scheduled_event_alerts[0]
                progress_logger.log_detail(
                    f"排期事件: {top.get('label')} {top.get('event_date')} "
                    f"({top.get('trading_days_until')}交易日, {top.get('severity')})"
                )
            progress_extra = (
                [f"分析师并行度: {workers}（市场/情绪/新闻/基本面同时跑）"]
                + prefetch_lines[:8]
                + progress_extra
            )
            if progress_logger:
                for line in progress_extra:
                    progress_logger.log_detail(line)
                progress_logger.set_activity_kind("llm")

        from tradingagents.agents.utils.position_holdings import (
            enrich_verified_with_position_holdings,
            get_holdings_from_config,
        )

        cost, shares = get_holdings_from_config(self.config)
        if cost is not None or shares is not None:
            verified_market_facts = enrich_verified_with_position_holdings(
                verified_market_facts, self.config
            )
            parts = []
            if cost is not None:
                parts.append(f"成本 {cost:g}")
            if shares is not None:
                parts.append(f"{shares} 股")
            progress_extra.append(f"持仓注入: {', '.join(parts)}")

        # Initialize state — inject memory log + post-audit lessons for PM.
        past_context = self.memory_log.get_past_context(company_name)
        try:
            from tradingagents.dataflows.backtest_audit_context import (
                format_compact_audit_context,
            )

            audit_ctx = format_compact_audit_context(
                self.config.get("results_dir") or "results",
                limit=5,
                ticker=company_name,
            )
            if audit_ctx:
                past_context = f"{past_context}\n\n{audit_ctx}".strip() if past_context else audit_ctx
        except Exception as exc:
            logger.warning("Backtest audit context injection skipped: %s", exc)
        parallel_analysts = (
            int(self.config.get("analyst_concurrency_limit", 1)) > 1
        )
        init_agent_state = self.propagator.create_initial_state(
            company_name,
            trade_date,
            asset_type=asset_type,
            past_context=past_context,
            parallel_analysts=parallel_analysts,
        )
        if verified_market_facts:
            init_agent_state["verified_market_facts"] = verified_market_facts
        if scheduled_event_alerts:
            init_agent_state["scheduled_event_alerts"] = scheduled_event_alerts

        tuige_setup = (self.config.get("tuige_setup") or "").strip()
        tuige_ctx_dict: Optional[Dict[str, Any]] = None
        tuige_position_grade = (self.config.get("tuige_position_grade") or "").strip()
        if not tuige_setup or not tuige_position_grade:
            try:
                from tradingagents.tuige.context import build_tuige_context, tuige_enabled
                from tradingagents.tuige.position_grade import (
                    derive_position_grade,
                    format_tuige_summary,
                )
                from tradingagents.tuige.setup_classifier import classify_setup_from_code

                if tuige_enabled() and cn_uses_a_share_skill(company_name, self.config):
                    if not tuige_setup:
                        cls = classify_setup_from_code(company_name, str(trade_date))
                        if cls and cls.setup != "unclassified":
                            tuige_setup = cls.setup
                    from tradingagents.tuige.market_inputs import fetch_tuige_market_inputs

                    market = fetch_tuige_market_inputs(str(trade_date))
                    ctx = build_tuige_context(
                        str(trade_date),
                        ticker=company_name,
                        quotes=market.quotes,
                        index_payload=market.index_payload,
                        industry_flows=market.industry_flows,
                        tuige_setup=tuige_setup or None,
                    )
                    if ctx.enabled:
                        tuige_ctx_dict = ctx.to_dict()
                        if not tuige_position_grade:
                            tuige_position_grade = derive_position_grade(
                                tuige_ctx_dict,
                                tuige_setup or "unclassified",
                            )
            except Exception as exc:
                logger.debug("Tuige setup/grade skipped: %s", exc)
        if tuige_setup:
            init_agent_state["tuige_setup"] = tuige_setup
            if progress_logger:
                progress_logger.log_detail(f"Tuige setup: {tuige_setup}")
        if tuige_position_grade:
            init_agent_state["tuige_position_grade"] = tuige_position_grade
            if progress_logger:
                progress_logger.log_detail(f"Tuige position_grade: {tuige_position_grade}")
        if tuige_ctx_dict:
            from tradingagents.tuige.position_grade import format_tuige_summary

            init_agent_state["tuige_context_summary"] = format_tuige_summary(tuige_ctx_dict)

        args = self.propagator.get_graph_args()

        # Inject thread_id so same ticker+date resumes, different date starts fresh.
        if self.config.get("checkpoint_enabled"):
            tid = thread_id(company_name, str(trade_date))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid

        if self.debug:
            trace = []
            for chunk in self.graph.stream(init_agent_state, **args):
                if len(chunk["messages"]) == 0:
                    pass
                else:
                    chunk["messages"][-1].pretty_print()
                    trace.append(chunk)
            # Streamed chunks are per-node deltas. Merge them so the returned
            # state matches what graph.invoke() yields in the non-debug path.
            final_state = {}
            for chunk in trace:
                final_state.update(chunk)
        elif progress_logging_enabled(self.config):
            if progress_logger is None:
                progress_logger = GraphProgressLogger(company_name, str(trade_date))
                progress_logger.log_start()
            final_state = progress_logger.run_stream(
                self.graph, init_agent_state, args
            )
        else:
            final_state = self.graph.invoke(init_agent_state, **args)

        grade = (final_state.get("tuige_position_grade") or tuige_position_grade or "").strip()
        setup = (final_state.get("tuige_setup") or tuige_setup or "").strip()
        if grade and final_state.get("final_trade_decision"):
            from tradingagents.tuige.position_grade import enrich_final_trade_decision

            summary = (final_state.get("tuige_context_summary") or "").strip()
            enriched = enrich_final_trade_decision(
                final_state["final_trade_decision"],
                position_grade=grade,
                tuige_setup=setup,
                tuige_summary=summary,
            )
            if enriched != final_state["final_trade_decision"]:
                final_state["final_trade_decision"] = enriched

        # Store current state for reflection.
        self.curr_state = final_state

        # Log state to disk (JSON + markdown).
        md_path = self._log_state(trade_date, final_state)
        if progress_logger is not None:
            progress_logger.log_finish(
                self.process_signal(final_state.get("final_trade_decision") or ""),
                md_report_path=str(md_path) if md_path else None,
            )

        # Store decision for deferred reflection on the next same-ticker run.
        self.memory_log.store_decision(
            ticker=company_name,
            trade_date=trade_date,
            final_trade_decision=final_state["final_trade_decision"],
        )

        # Clear checkpoint on successful completion to avoid stale state.
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"], company_name, str(trade_date)
            )

        return final_state, self.process_signal(final_state["final_trade_decision"])

    def _log_state(self, trade_date, final_state) -> Optional[Path]:
        """Log final state to JSON and markdown; return path to complete_report.md."""
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }

        bundle = report_bundle_dir(self.config["results_dir"], self.ticker, trade_date)
        bundle.mkdir(parents=True, exist_ok=True)
        bundle_label = build_report_bundle_name(self.ticker, trade_date)

        log_path = bundle / f"{bundle_label}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4)

        complete_report_text = ""
        md_path = None
        if self.config.get("save_md", True):
            md_path = save_analysis_report_md(
                final_state,
                self.ticker,
                bundle,
                trade_date=str(trade_date),
                stock_name=resolve_stock_display_name(self.ticker),
            )
            logger.info("Markdown report written to %s", md_path)
            if md_path and md_path.is_file():
                complete_report_text = md_path.read_text(encoding="utf-8")

        sync_analysis_report_sqlite(
            final_state,
            self.ticker,
            str(trade_date),
            complete_report_text=complete_report_text,
            results_dir=self.config["results_dir"],
        )
        return md_path

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
