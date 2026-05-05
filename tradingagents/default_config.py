import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
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
    # Market profile. KR is the local fork's primary target, but the data
    # router falls back to the original US-capable yfinance/Alpha Vantage
    # vendors when the ticker is not a Korean 6-digit code.
    "market": os.getenv("TRADINGAGENTS_MARKET", "KR"),
    "currency": os.getenv("TRADINGAGENTS_CURRENCY", "KRW"),
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "pykrx,krx,yfinance",       # Options: pykrx, krx, alpha_vantage, yfinance
        "technical_indicators": "pykrx,krx,yfinance",  # Options: pykrx, krx, alpha_vantage, yfinance
        "fundamental_data": "dart,yfinance",       # Options: dart, alpha_vantage, yfinance
        "news_data": "naver,dart,yfinance",        # Options: naver, dart, alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    "korea": {
        "timezone": "Asia/Seoul",
        "regular_session": "09:00-15:30",
        "currency": "KRW",
        "benchmark_by_market": {
            "KOSPI": "^KS11",
            "KOSDAQ": "^KQ11",
            "KONEX": "^KS11",
            "UNKNOWN": "^KS11",
        },
        "broker": {
            "provider": "kis",
            "paper": os.getenv("KIS_IS_PAPER", "true").strip().lower() != "false",
            "account_no": os.getenv("KIS_ACCOUNT_NO") or os.getenv("KIS_CANO"),
            "account_product_code": os.getenv("KIS_ACCOUNT_PRODUCT_CODE") or os.getenv("KIS_ACNT_PRDT_CD"),
        },
    },
}
