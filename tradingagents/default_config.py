import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")
_LOCAL_TRADINGAGENTS_HOME = os.path.join(os.getcwd(), ".tradingagents")


def _storage_dir_writable(path: str) -> bool:
    """True when the directory exists and we can create/append a probe file."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_probe")
        with open(probe, "a", encoding="utf-8"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def _default_storage_dir(subdir: str, *, env_var: str | None = None) -> str:
    """Pick a writable storage directory (home dir, or project-local fallback)."""
    explicit = os.environ.get(env_var) if env_var else None
    if explicit:
        path = os.path.abspath(os.path.expanduser(explicit))
        if _storage_dir_writable(path):
            return path
        fallback = os.path.abspath(os.path.join(_LOCAL_TRADINGAGENTS_HOME, subdir))
        if _storage_dir_writable(fallback):
            return fallback
        os.makedirs(fallback, exist_ok=True)
        return fallback

    home_path = os.path.join(_TRADINGAGENTS_HOME, subdir)
    if _storage_dir_writable(home_path):
        return home_path
    fallback = os.path.abspath(os.path.join(_LOCAL_TRADINGAGENTS_HOME, subdir))
    if _storage_dir_writable(fallback):
        return fallback
    os.makedirs(fallback, exist_ok=True)
    return fallback


def _default_memory_log_path() -> str:
    explicit = os.environ.get("TRADINGAGENTS_MEMORY_LOG_PATH")
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    memory_dir = _default_storage_dir("memory")
    return os.path.join(memory_dir, "trading_memory.md")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_MARKET":               "market_profile",
    "TRADINGAGENTS_GLOBAL_NEWS_MODE":     "global_news_mode",
    "TRADINGAGENTS_PROGRESS_LOG":        "progress_logging",
    "TRADINGAGENTS_ANALYST_CONCURRENCY": "analyst_concurrency_limit",
    "TRADINGAGENTS_RESULTS_DIR":         "results_dir",
    "TRADINGAGENTS_CACHE_DIR":           "data_cache_dir",
    "TRADINGAGENTS_MEMORY_LOG_PATH":     "memory_log_path",
    "TRADINGAGENTS_POSITION_CONTEXT":    "position_context",
}


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value."""
    if isinstance(reference, bool):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        config[key] = _coerce(raw, config.get(key))
    return config


# CN ``get_global_news`` base queries: macro/policy only (not per-sector boards).
# Per-stock industry queries are appended at runtime via ``ticker_news_queries``.
CN_GLOBAL_NEWS_QUERIES = [
    # 宏观 / 政策 / 资金（少量；板块由 ticker 行业动态追加）
    "中国人民银行 货币政策 LPR 降准",
    "A股 沪深300 北向资金 成交额 两市",
    "证监会 政策 监管 立案 处罚",
    "国务院 财政 专项债 化债 地方债",
    "中美贸易 关税 出口 汇率",
]


def _cn_market_defaults() -> dict:
    """Defaults applied when ``market_profile`` is ``cn``."""
    return {
        "output_language": "Chinese",
        # CN: all market data via ~/.cursor/skills/a-share-data/run.sh (no Yahoo/AlphaVantage).
        "data_vendors": {
            "core_stock_apis": "a_share",
            "technical_indicators": "a_share",
            "fundamental_data": "a_share",
            "news_data": "a_share",
        },
        # macro_plus_ticker: CN_GLOBAL_NEWS_QUERIES + ticker_news_queries (default)
        "global_news_mode": "macro_plus_ticker",
        "global_news_article_limit": 15,
        "global_news_queries": list(CN_GLOBAL_NEWS_QUERIES),
        # Optional extra codes for TTM PE comparison table (empty = primary ticker only).
        # Set per run in config/env if needed, e.g. hydropower peers for 600900.
        "cn_valuation_peers": [],
        "require_verified_valuation": True,
        "benchmark_map": {
            ".NS": "^NSEI",
            ".BO": "^BSESN",
            ".T": "^N225",
            ".HK": "^HSI",
            ".L": "^FTSE",
            ".TO": "^GSPTSE",
            ".AX": "^AXJO",
            ".SS": "000300.SS",
            ".SZ": "000300.SS",
            ".SH": "000300.SS",
            "": "000300.SS",
        },
    }


def apply_market_profile(config: dict) -> dict:
    """Merge China A-share defaults when ``market_profile`` is ``cn`` or ``auto``+ticker."""
    profile = (config.get("market_profile") or "us").strip().lower()
    if profile in ("cn", "a", "a_share", "china"):
        overrides = _cn_market_defaults()
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                merged = dict(config[key])
                merged.update(value)
                config[key] = merged
            else:
                config[key] = value
    return config


DEFAULT_CONFIG = apply_market_profile(_apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": _default_storage_dir("logs", env_var="TRADINGAGENTS_RESULTS_DIR"),
    "data_cache_dir": _default_storage_dir("cache", env_var="TRADINGAGENTS_CACHE_DIR"),
    "memory_log_path": _default_memory_log_path(),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # Market: "us" (default), "cn" (A-share via a-share-data skill), or "auto"
    "market_profile": "us",
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Decision framing: "empty" (flat, no position — default) or "held" (already own the ticker)
    "position_context": "empty",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # >1 runs market/sentiment/news/fundamentals in parallel (LangGraph fan-out).
    # Use 1 until parallel join/debate reducers are fully battle-tested.
    "analyst_concurrency_limit": 1,
    # Print stage-by-stage progress to stderr during propagate (off: TRADINGAGENTS_PROGRESS_LOG=0)
    "progress_logging": True,
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # get_global_news query merge: macro_plus_ticker | macro_only | ticker_only
    "global_news_mode": "macro_plus_ticker",
    # Per-run industry queries (filled in propagate for CN tickers).
    "ticker_news_queries": [],
    # Set per propagate(); used by a_share news fetchers (no Yahoo).
    "company_of_interest": None,
    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",    # NSE India (Nifty 50)
        ".BO":  "^BSESN",   # BSE India (Sensex)
        ".T":   "^N225",    # Tokyo (Nikkei 225)
        ".HK":  "^HSI",     # Hong Kong (Hang Seng)
        ".L":   "^FTSE",    # London (FTSE 100)
        ".TO":  "^GSPTSE",  # Toronto (TSX Composite)
        ".AX":  "^AXJO",    # Australia (ASX 200)
        "":     "SPY",      # default for US-listed tickers (no suffix)
    },
}))
