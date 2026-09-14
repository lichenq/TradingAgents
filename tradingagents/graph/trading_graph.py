# TradingAgents/graph/trading_graph.py

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yfinance as yf
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
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
from tradingagents.dataflows.sector_queries import apply_ticker_news_queries

# Import the abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_global_news,
    get_income_statement,
    get_indicators,
    get_insider_transactions,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
    get_stock_data,
    get_verified_market_snapshot,
    resolve_instrument_identity,
)
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.reporting import write_report_tree

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .propagation import Propagator
from .reflection import Reflector
from .setup import GraphSetup
from .signal_processing import SignalProcessor
from .progress_log import GraphProgressLogger, progress_logging_enabled
from .report_export import save_analysis_report_md, sync_analysis_report_sqlite

logger = logging.getLogger(__name__)


def _coerce_max_retries(value):
    """Validate an ``llm_max_retries`` value to a non-negative int.

    Accepts an int or a numeric string (env vars arrive as strings). Rejects
    booleans and negatives loudly so a misconfiguration fails at startup rather
    than silently disabling retries.
    """
    if isinstance(value, bool):
        raise ValueError(f"llm_max_retries must be an integer, not a boolean: {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"llm_max_retries must be an integer, got {value!r}") from exc
    if n < 0:
        raise ValueError(f"llm_max_retries must be >= 0, got {n}")
    return n


def _coerce_max_tokens(value):
    """Validate a ``max_tokens`` value to a positive int (env vars are strings)."""
    if isinstance(value, bool):
        raise ValueError(f"max_tokens must be an integer, not a boolean: {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"max_tokens must be an integer, got {value!r}") from exc
    if n <= 0:
        raise ValueError(f"max_tokens must be > 0, got {n}")
    return n


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=("market", "social", "news", "fundamentals"),
        debug=False,
        config: dict[str, Any] = None,
        callbacks: list | None = None,
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

        # Graph-shape-affecting run choices, kept for the checkpoint signature.
        self.selected_analysts = tuple(selected_analysts)

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        self.workflow = self.graph_setup.setup_graph(selected_analysts)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None
        self._resuming = False

    def _get_provider_kwargs(self) -> dict[str, Any]:
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

        # Sampling temperature is cross-provider: forward it whenever set.
        # float() here so a value coming from a TRADINGAGENTS_TEMPERATURE env
        # string ("0.2") works the same as a programmatic float.
        temperature = self.config.get("temperature")
        if temperature is not None and temperature != "":
            kwargs["temperature"] = float(temperature)

        # SDK retry budget is cross-provider. Forward it only when explicitly set
        # so each provider keeps its own default (usually 2) otherwise (#1091).
        max_retries = self.config.get("llm_max_retries")
        if max_retries is not None and max_retries != "":
            kwargs["max_retries"] = _coerce_max_retries(max_retries)

        # Output-token cap is cross-provider, but Gemini names it
        # ``max_output_tokens``; forward under the right key when set (#1204).
        max_tokens = self.config.get("max_tokens")
        if max_tokens is not None and max_tokens != "":
            key = "max_output_tokens" if provider == "google" else "max_tokens"
            kwargs[key] = _coerce_max_tokens(max_tokens)

        return kwargs

    def _create_tool_nodes(self) -> dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                    # Deterministic verification snapshot (bound to the analyst
                    # LLM and required by its prompt; must be executable here or
                    # the call fails and the model reports it "unavailable").
                    get_verified_market_snapshot,
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
                    get_macro_indicators,
                    get_prediction_markets,
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
    ) -> tuple[float | None, float | None, int | None, str | None]:
        """Fetch raw and alpha return for ticker over holding_days from trade_date.

        ``benchmark`` is the index used as the alpha baseline (resolved by the
        caller via ``_resolve_benchmark``). Returns ``(raw_return, alpha_return,
        holding_days, resolution_date)`` — where ``resolution_date`` is the date
        of the last price bar used, i.e. when the outcome became known (#1251) —
        or ``(None, None, None, None)`` when the outcome cannot be settled yet:
        the full holding window has not traded (#1169), or the symbol is delisted
        or unreachable.
        """
        from tradingagents.dataflows.symbol_utils import normalize_symbol

        # Tolerate unbound/spec-mock calls where the instance carries no config.
        config = getattr(self, "config", None) or {}
        try:
            from tradingagents.market import cn_uses_a_share_skill
            from tradingagents.dataflows.a_share_returns import fetch_raw_and_alpha_returns

            if cn_uses_a_share_skill(ticker, config):
                return fetch_raw_and_alpha_returns(
                    ticker, benchmark, trade_date, holding_days
                )

            start = datetime.strptime(trade_date, "%Y-%m-%d")
            end = start + timedelta(days=holding_days + 7)  # buffer for weekends/holidays
            end_str = end.strftime("%Y-%m-%d")

            # Normalize so the realized-return lookup hits the same instrument
            # the analysis priced (e.g. XAUUSD -> GC=F) (#984). The benchmark is
            # already a canonical Yahoo symbol from ``_resolve_benchmark``.
            stock = yf.Ticker(normalize_symbol(ticker)).history(start=trade_date, end=end_str)
            bench = yf.Ticker(benchmark).history(start=trade_date, end=end_str)

            # Require the full holding window in both series. A rerun before it
            # has traded leaves the entry pending to retry next run, rather than
            # settling on a premature partial return (#1169).
            if len(stock) <= holding_days or len(bench) <= holding_days:
                return None, None, None, None

            raw = float(
                (stock["Close"].iloc[holding_days] - stock["Close"].iloc[0])
                / stock["Close"].iloc[0]
            )
            bench_ret = float(
                (bench["Close"].iloc[holding_days] - bench["Close"].iloc[0])
                / bench["Close"].iloc[0]
            )
            alpha = raw - bench_ret
            # The date of the last price bar used is when this outcome became
            # known — the point-in-time cutoff for injecting the lesson (#1251).
            resolution_date = stock.index[holding_days].strftime("%Y-%m-%d")
            return raw, alpha, holding_days, resolution_date
        except Exception as e:
            logger.warning(
                "Could not resolve outcome for %s on %s vs %s (will retry next run): %s",
                ticker, trade_date, benchmark, e,
            )
            return None, None, None, None

    def _resolve_pending_entries(self, ticker: str) -> None:
        """Resolve pending log entries whose outcome data is available."""
        pending = self.memory_log.get_pending_entries()
        config = getattr(self, "config", None) or {}
        max_resolve = int(config.get("max_pending_resolve_per_run", 2))
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
            raw, alpha, days, resolution_date = self._fetch_returns(
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
                "resolution_date": resolution_date,
            })

        if updates:
            self.memory_log.batch_update_with_outcomes(updates)

    def resolve_instrument_context(self, ticker: str, asset_type: str = "stock") -> str:
        """Resolve ticker identity once and return the full instrument context.

        Deterministic yfinance lookup (cached, fail-open) injected into a
        context string so every agent anchors to the real company instead of
        hallucinating one from the price chart (#814). Both the propagate()
        path and the CLI call this so the resolved identity reaches the whole
        graph regardless of entry point.
        """
        identity = resolve_instrument_identity(ticker)
        return build_instrument_context(ticker, asset_type, identity)

    def _memory_as_of(self, trade_date) -> str | None:
        """Point-in-time cutoff for past-context lessons (#1251).

        A historical/backtest run (trade date before today) filters lessons to
        those already resolved by the trade date. A current-date run returns
        None, disabling the filter so live behavior and pre-migration entries
        (which have no stored resolution date) are unaffected.
        """
        td = str(trade_date)
        return td if td < datetime.now().strftime("%Y-%m-%d") else None

    def _run_signature(self, asset_type: str) -> str:
        """Graph-shape inputs that must invalidate a checkpoint if changed.

        Keyed into the checkpoint thread ID so a resume under a different analyst
        selection, debate/risk depth, or asset mode starts fresh instead of
        silently continuing the previous graph (#1089).
        """
        return "|".join([
            "analysts=" + ",".join(self.selected_analysts),
            f"debate={self.config['max_debate_rounds']}",
            f"risk={self.config['max_risk_discuss_rounds']}",
            f"asset={asset_type}",
        ])

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

        Returns ``(final_state, signal)`` where ``signal`` is one of the 5-tier
        ratings (Buy / Overweight / Hold / Underweight / Sell) or ``"REVIEW"``
        when the decision had no parseable rating (#1170); guard with
        ``tradingagents.agents.utils.rating.is_review`` before mapping it to the
        PortfolioRating enum.
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

        with self.checkpoint_scope(company_name, trade_date, asset_type) as thread_id_value:
            return self._run_graph(
                company_name, trade_date, asset_type=asset_type,
                checkpoint_thread_id=thread_id_value,
                progress_logger=progress_logger,
            )

    def begin_checkpoint(self, company_name, trade_date, asset_type: str = "stock") -> str | None:
        """Recompile the graph with a per-ticker checkpointer and return the
        ``thread_id`` to inject into the stream/invoke ``config`` (or ``None``
        when checkpointing is disabled).

        Pair every call with :meth:`end_checkpoint` in a ``finally``. Both
        ``propagate`` (via :meth:`checkpoint_scope`) and the CLI stream path use
        this so ``--checkpoint`` actually resumes (#1249); previously the setup
        lived only inside ``propagate`` and the CLI streamed the checkpointer-less
        graph, making the flag a no-op.
        """
        self._resuming = False
        if not self.config.get("checkpoint_enabled"):
            return None
        signature = self._run_signature(asset_type)
        self._checkpointer_ctx = get_checkpointer(self.config["data_cache_dir"], company_name)
        saver = self._checkpointer_ctx.__enter__()
        self.graph = self.workflow.compile(checkpointer=saver)

        step = checkpoint_step(
            self.config["data_cache_dir"], company_name, str(trade_date), signature
        )
        self._resuming = step is not None
        if step is not None:
            logger.info("Resuming from step %d for %s on %s", step, company_name, trade_date)
        else:
            logger.info("Starting fresh for %s on %s", company_name, trade_date)
        return thread_id(company_name, str(trade_date), signature)

    def checkpoint_input(self, init_state):
        """The value to stream/invoke: ``None`` to resume an existing checkpoint,
        else the initial state for a fresh run.

        LangGraph resumes an interrupted thread when invoked with ``None``;
        re-passing the initial state instead appends it through the message
        reducer, duplicating messages in the resumed state (#1249).
        """
        return None if self._resuming else init_state

    def end_checkpoint(self):
        """Restore the plain uncheckpointed graph after a checkpointed run."""
        if self._checkpointer_ctx is not None:
            self._checkpointer_ctx.__exit__(None, None, None)
            self._checkpointer_ctx = None
            self.graph = self.workflow.compile()
        self._resuming = False

    @contextmanager
    def checkpoint_scope(self, company_name, trade_date, asset_type: str = "stock"):
        """Context-manager form of begin/end_checkpoint for the propagate path."""
        try:
            yield self.begin_checkpoint(company_name, trade_date, asset_type)
        finally:
            self.end_checkpoint()

    def clear_checkpoint_on_success(self, company_name, trade_date, asset_type: str = "stock"):
        """Drop a completed run's checkpoint so a later run starts fresh (#1249)."""
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"], company_name, str(trade_date),
                self._run_signature(asset_type),
            )

    def save_reports(self, final_state, ticker, save_path=None) -> Path:
        """Write the markdown report tree for a completed run, like the CLI does.

        Programmatic callers get the same on-disk reports the CLI produces. Pass
        an explicit ``save_path`` or let it default under ``results_dir``.
        """
        if save_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = (
                Path(self.config["results_dir"])
                / "reports"
                / f"{safe_ticker_component(ticker)}_{stamp}"
            )
        return write_report_tree(final_state, ticker, save_path)

    def _run_graph(
        self,
        company_name,
        trade_date,
        asset_type: str = "stock",
        checkpoint_thread_id: str | None = None,
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

        # Initialize state — inject memory log context for PM and the
        # deterministically resolved instrument identity for all agents. On a
        # historical run, gate lessons to those whose outcome was known by the
        # trade date so a backtest can't learn from the future (#1251).
        past_context = self.memory_log.get_past_context(
            company_name, as_of=self._memory_as_of(trade_date)
        )
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
        instrument_context = self.resolve_instrument_context(company_name, asset_type)
        init_agent_state = self.propagator.create_initial_state(
            company_name,
            trade_date,
            asset_type=asset_type,
            past_context=past_context,
            parallel_analysts=parallel_analysts,
            instrument_context=instrument_context,
        )
        if verified_market_facts:
            init_agent_state["verified_market_facts"] = verified_market_facts
        if scheduled_event_alerts:
            init_agent_state["scheduled_event_alerts"] = scheduled_event_alerts

        tuige_setup = (self.config.get("tuige_setup") or "").strip()
        tuige_ctx_dict: Optional[Dict[str, Any]] = None
        tuige_position_grade = (self.config.get("tuige_position_grade") or "").strip()
        try:
            from tradingagents.tuige.context import build_tuige_context, tuige_enabled
            from tradingagents.tuige.position_grade import derive_position_grade
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

            init_agent_state["tuige_context"] = tuige_ctx_dict
            init_agent_state["tuige_context_summary"] = format_tuige_summary(tuige_ctx_dict)

        args = self.propagator.get_graph_args()

        # Inject the checkpoint thread_id (from checkpoint_scope) so the same
        # ticker+date+graph-shape resumes; a different one starts fresh (#1089).
        if checkpoint_thread_id is not None:
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = checkpoint_thread_id

        # None resumes an existing checkpoint; init_agent_state starts fresh (#1249).
        graph_input = self.checkpoint_input(init_agent_state)
        if self.debug:
            trace = []
            last_printed = None
            for chunk in self.graph.stream(graph_input, **args):
                if chunk["messages"]:
                    msg = chunk["messages"][-1]
                    # Nodes after the trader don't append to messages, so the
                    # same trailing message repeats across chunks. Print it only
                    # when it changes (#1027); the trace/state merge is unchanged.
                    signature = (type(msg).__name__, getattr(msg, "content", None))
                    if signature != last_printed:
                        msg.pretty_print()
                        last_printed = signature
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
                self.graph, graph_input, args
            )
        else:
            final_state = self.graph.invoke(graph_input, **args)

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
        self.clear_checkpoint_on_success(company_name, trade_date, asset_type)

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
