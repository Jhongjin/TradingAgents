"""Risk metrics for price series and equity curves.

All functions accept plain Python sequences so they work with chart points,
backtest equity curves, and pandas Series alike.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from statistics import mean, pstdev
from typing import Any, Iterable, Sequence


TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class RiskSummary:
    observations: int
    total_return: float | None
    annualized_return: float | None
    annualized_volatility: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown: float | None
    value_at_risk_95: float | None
    conditional_value_at_risk_95: float | None
    beta: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def returns_from_prices(prices: Iterable[float]) -> list[float]:
    """Simple daily returns from a close-price sequence (non-positive prices are skipped)."""

    cleaned = [float(price) for price in prices if price is not None and float(price) > 0]
    return [(current / previous) - 1 for previous, current in zip(cleaned[:-1], cleaned[1:])]


def annualized_volatility(returns: Sequence[float], periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float | None:
    if len(returns) < 2:
        return None
    return pstdev(returns) * sqrt(periods_per_year)


def sharpe_ratio(
    returns: Sequence[float],
    *,
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float | None:
    if len(returns) < 2:
        return None
    excess = [value - (risk_free_rate / periods_per_year) for value in returns]
    deviation = pstdev(excess)
    if deviation == 0:
        return None
    return (mean(excess) / deviation) * sqrt(periods_per_year)


def sortino_ratio(
    returns: Sequence[float],
    *,
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float | None:
    if len(returns) < 2:
        return None
    target = risk_free_rate / periods_per_year
    excess = [value - target for value in returns]
    downside = [min(value, 0.0) ** 2 for value in excess]
    downside_deviation = sqrt(sum(downside) / len(downside))
    if downside_deviation == 0:
        return None
    return (mean(excess) / downside_deviation) * sqrt(periods_per_year)


def max_drawdown(prices: Iterable[float]) -> float | None:
    """Largest peak-to-trough decline expressed as a negative fraction."""

    peak: float | None = None
    worst = 0.0
    seen = False
    for price in prices:
        if price is None:
            continue
        value = float(price)
        if value <= 0:
            continue
        seen = True
        if peak is None or value > peak:
            peak = value
        drawdown = (value / peak) - 1
        if drawdown < worst:
            worst = drawdown
    return worst if seen else None


def value_at_risk(returns: Sequence[float], confidence: float = 0.95) -> float | None:
    """Historical VaR as a positive loss fraction (e.g. 0.03 means a 3% loss)."""

    if not returns:
        return None
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    ordered = sorted(float(value) for value in returns)
    index = int((1 - confidence) * len(ordered))
    index = min(max(index, 0), len(ordered) - 1)
    return max(-ordered[index], 0.0)


def conditional_value_at_risk(returns: Sequence[float], confidence: float = 0.95) -> float | None:
    """Expected shortfall beyond the VaR threshold, as a positive loss fraction."""

    if not returns:
        return None
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    ordered = sorted(float(value) for value in returns)
    cutoff = int((1 - confidence) * len(ordered))
    tail = ordered[: max(cutoff, 1)]
    return max(-mean(tail), 0.0)


def beta(asset_returns: Sequence[float], benchmark_returns: Sequence[float]) -> float | None:
    pairs = [(float(a), float(b)) for a, b in zip(asset_returns, benchmark_returns)]
    if len(pairs) < 2:
        return None
    asset_mean = mean(pair[0] for pair in pairs)
    benchmark_mean = mean(pair[1] for pair in pairs)
    covariance = sum((a - asset_mean) * (b - benchmark_mean) for a, b in pairs) / len(pairs)
    variance = sum((b - benchmark_mean) ** 2 for _, b in pairs) / len(pairs)
    if variance == 0:
        return None
    return covariance / variance


def risk_summary(
    prices: Iterable[float],
    *,
    benchmark_prices: Iterable[float] | None = None,
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> RiskSummary:
    """Compute a compact, JSON-ready risk profile for a close-price series."""

    cleaned = [float(price) for price in prices if price is not None and float(price) > 0]
    returns = returns_from_prices(cleaned)
    total_return = (cleaned[-1] / cleaned[0]) - 1 if len(cleaned) >= 2 else None
    annualized_return = None
    if total_return is not None and len(returns) > 0:
        years = len(returns) / periods_per_year
        if years > 0 and (1 + total_return) > 0:
            annualized_return = (1 + total_return) ** (1 / years) - 1
    asset_beta = None
    if benchmark_prices is not None:
        benchmark_returns = returns_from_prices(benchmark_prices)
        asset_beta = beta(returns, benchmark_returns)
    return RiskSummary(
        observations=len(cleaned),
        total_return=_round(total_return),
        annualized_return=_round(annualized_return),
        annualized_volatility=_round(annualized_volatility(returns, periods_per_year)),
        sharpe_ratio=_round(sharpe_ratio(returns, risk_free_rate=risk_free_rate, periods_per_year=periods_per_year)),
        sortino_ratio=_round(sortino_ratio(returns, risk_free_rate=risk_free_rate, periods_per_year=periods_per_year)),
        max_drawdown=_round(max_drawdown(cleaned)),
        value_at_risk_95=_round(value_at_risk(returns, 0.95)),
        conditional_value_at_risk_95=_round(conditional_value_at_risk(returns, 0.95)),
        beta=_round(asset_beta),
    )


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)
