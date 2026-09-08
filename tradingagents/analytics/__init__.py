"""Deterministic quantitative analytics shared by screener, harness, and reports.

The metrics here are inspired by the risk/quant modules in FinceptTerminal and
Vibe-Trading's quantlib (VaR/CVaR, Sharpe, drawdown, inverse-volatility
weights). They are intentionally dependency-light so they can run inside the
public API, the CLI, and unit tests without a GPU or external service.
"""

from .portfolio import (
    DiversificationSuggestion,
    PortfolioWeights,
    concentration_report,
    correlation_matrix,
    inverse_volatility_weights,
    suggest_diversification,
)
from .risk_metrics import (
    RiskSummary,
    annualized_volatility,
    beta,
    conditional_value_at_risk,
    max_drawdown,
    returns_from_prices,
    risk_summary,
    sharpe_ratio,
    sortino_ratio,
    value_at_risk,
)

__all__ = [
    "DiversificationSuggestion",
    "PortfolioWeights",
    "RiskSummary",
    "annualized_volatility",
    "beta",
    "concentration_report",
    "conditional_value_at_risk",
    "correlation_matrix",
    "inverse_volatility_weights",
    "max_drawdown",
    "returns_from_prices",
    "risk_summary",
    "sharpe_ratio",
    "sortino_ratio",
    "suggest_diversification",
    "value_at_risk",
]
