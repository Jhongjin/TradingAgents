"""Korean-market stock screener.

This package borrows the "Alpha Zoo" idea from Vibe-Trading and the
deterministic pre-filter stage from Binance-Agent: a rule-based scanner ranks
the KOSPI/KOSDAQ universe on transparent factors before any LLM is consulted.
The output is a candidate list that the analysis harness can confirm or
reject, so expensive multi-agent runs are spent only on promising names.
"""

from .factors import FactorScores, compute_factor_scores
from .screener import (
    ScreenerCandidate,
    ScreenerConfig,
    ScreenerResult,
    screen_korean_market,
)
from .universe import (
    MarketSnapshot,
    MarketSnapshotRow,
    build_snapshot_from_history,
    fallback_universe_codes,
    load_index_snapshot,
    load_market_snapshot,
)

__all__ = [
    "FactorScores",
    "MarketSnapshot",
    "MarketSnapshotRow",
    "ScreenerCandidate",
    "ScreenerConfig",
    "ScreenerResult",
    "build_snapshot_from_history",
    "compute_factor_scores",
    "fallback_universe_codes",
    "load_index_snapshot",
    "load_market_snapshot",
    "screen_korean_market",
]
