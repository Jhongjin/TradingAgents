"""Portfolio construction helpers: inverse-volatility weights and diversification hints."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import mean, pstdev
from typing import Any, Mapping, Sequence

from .risk_metrics import returns_from_prices


@dataclass(frozen=True)
class PortfolioWeights:
    weights: dict[str, float]
    method: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiversificationSuggestion:
    concentration: dict[str, Any]
    highly_correlated_pairs: list[dict[str, Any]]
    suggestions: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def inverse_volatility_weights(
    price_history: Mapping[str, Sequence[float]],
    *,
    max_weight: float = 0.25,
    min_observations: int = 20,
) -> PortfolioWeights:
    """Weight assets by inverse realised volatility, capped per position.

    Excess weight above the cap is left in cash rather than force-fed into the
    remaining names, which keeps the result conservative for paper trading.
    """

    if not 0 < max_weight <= 1:
        raise ValueError("max_weight must be between 0 and 1")
    inverse: dict[str, float] = {}
    notes: list[str] = []
    for ticker, prices in price_history.items():
        returns = returns_from_prices(prices)
        if len(returns) < min_observations:
            notes.append(f"{ticker}: insufficient history ({len(returns)} returns), excluded")
            continue
        volatility = pstdev(returns)
        if volatility <= 0:
            notes.append(f"{ticker}: zero volatility, excluded")
            continue
        inverse[ticker] = 1 / volatility
    if not inverse:
        return PortfolioWeights(weights={}, method="inverse_volatility", notes=notes)

    total = sum(inverse.values())
    raw = {ticker: value / total for ticker, value in inverse.items()}
    capped = {ticker: min(weight, max_weight) for ticker, weight in raw.items()}
    cash = 1 - sum(capped.values())
    if cash > 1e-9:
        notes.append(f"cash reserve {cash:.4f} after applying max_weight={max_weight}")
    return PortfolioWeights(
        weights={ticker: round(weight, 6) for ticker, weight in capped.items()},
        method="inverse_volatility",
        notes=notes,
    )


def correlation_matrix(price_history: Mapping[str, Sequence[float]]) -> dict[str, dict[str, float]]:
    """Pearson correlation of daily returns, aligned on the shortest series."""

    returns = {ticker: returns_from_prices(prices) for ticker, prices in price_history.items()}
    returns = {ticker: values for ticker, values in returns.items() if len(values) >= 2}
    if not returns:
        return {}
    length = min(len(values) for values in returns.values())
    aligned = {ticker: values[-length:] for ticker, values in returns.items()}
    matrix: dict[str, dict[str, float]] = {}
    for left, left_values in aligned.items():
        matrix[left] = {}
        for right, right_values in aligned.items():
            matrix[left][right] = round(_pearson(left_values, right_values), 6)
    return matrix


def concentration_report(weights: Mapping[str, float]) -> dict[str, Any]:
    """Herfindahl-style concentration diagnostics for a weight map."""

    cleaned = {ticker: float(weight) for ticker, weight in weights.items() if weight is not None and float(weight) > 0}
    total = sum(cleaned.values())
    if total <= 0:
        return {"position_count": 0, "gross_weight": 0.0, "hhi": None, "effective_positions": None, "largest_weight": None}
    normalized = {ticker: weight / total for ticker, weight in cleaned.items()}
    hhi = sum(weight ** 2 for weight in normalized.values())
    largest_ticker = max(normalized, key=normalized.get)
    return {
        "position_count": len(cleaned),
        "gross_weight": round(total, 6),
        "hhi": round(hhi, 6),
        "effective_positions": round(1 / hhi, 4),
        "largest_weight": round(cleaned[largest_ticker], 6),
        "largest_ticker": largest_ticker,
    }


def suggest_diversification(
    weights: Mapping[str, float],
    price_history: Mapping[str, Sequence[float]] | None = None,
    *,
    max_single_weight: float = 0.25,
    correlation_threshold: float = 0.75,
    candidate_pool: Mapping[str, Sequence[float]] | None = None,
) -> DiversificationSuggestion:
    """Deterministic diversification hints used by the harness' portfolio step.

    Suggestions flag oversized positions, highly correlated pairs, and (when a
    candidate pool is supplied) lowest-correlation additions from that pool.
    """

    concentration = concentration_report(weights)
    suggestions: list[str] = []
    if concentration["position_count"] == 0:
        suggestions.append("포트폴리오가 비어 있습니다. 후보군에서 상관관계가 낮은 종목부터 소액으로 편입하세요.")
    if concentration.get("largest_weight") and concentration["largest_weight"] > max_single_weight:
        suggestions.append(
            f"{concentration['largest_ticker']} 비중 {concentration['largest_weight']:.1%}이 한도 {max_single_weight:.0%}를 초과합니다. 비중 축소를 검토하세요."
        )
    if concentration.get("effective_positions") is not None and concentration["effective_positions"] < 3:
        suggestions.append("유효 종목 수가 3개 미만입니다. 서로 다른 업종/요인의 종목을 추가해 집중 위험을 낮추세요.")

    pairs: list[dict[str, Any]] = []
    matrix = correlation_matrix(price_history) if price_history else {}
    tickers = list(matrix)
    for index, left in enumerate(tickers):
        for right in tickers[index + 1 :]:
            value = matrix[left][right]
            if value >= correlation_threshold:
                pairs.append({"left": left, "right": right, "correlation": value})
    if pairs:
        pair_text = ", ".join(f"{pair['left']}-{pair['right']}({pair['correlation']:.2f})" for pair in pairs)
        suggestions.append(f"상관관계가 높은 조합이 있습니다: {pair_text}. 한 종목을 다른 요인의 종목으로 교체하는 것을 검토하세요.")

    if candidate_pool and price_history:
        held_returns = {ticker: returns_from_prices(prices) for ticker, prices in price_history.items()}
        held_returns = {ticker: values for ticker, values in held_returns.items() if len(values) >= 2}
        ranked: list[tuple[float, str]] = []
        for candidate, prices in candidate_pool.items():
            if candidate in weights:
                continue
            candidate_returns = returns_from_prices(prices)
            if len(candidate_returns) < 2 or not held_returns:
                continue
            correlations = []
            for values in held_returns.values():
                length = min(len(values), len(candidate_returns))
                correlations.append(_pearson(values[-length:], candidate_returns[-length:]))
            ranked.append((mean(correlations), candidate))
        ranked.sort()
        if ranked:
            best = ", ".join(f"{ticker}(평균 상관 {value:.2f})" for value, ticker in ranked[:3])
            suggestions.append(f"보유 종목과 상관관계가 낮은 후보: {best}.")

    return DiversificationSuggestion(concentration=concentration, highly_correlated_pairs=pairs, suggestions=suggestions)


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean = mean(left)
    right_mean = mean(right)
    covariance = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_var = sum((a - left_mean) ** 2 for a in left)
    right_var = sum((b - right_mean) ** 2 for b in right)
    if left_var == 0 or right_var == 0:
        return 0.0
    return covariance / ((left_var ** 0.5) * (right_var ** 0.5))
