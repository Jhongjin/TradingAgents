import math

import pytest

from tradingagents.analytics import (
    concentration_report,
    conditional_value_at_risk,
    correlation_matrix,
    inverse_volatility_weights,
    max_drawdown,
    returns_from_prices,
    risk_summary,
    sharpe_ratio,
    suggest_diversification,
    value_at_risk,
)


def test_returns_and_drawdown():
    prices = [100, 110, 99, 120, 90]
    returns = returns_from_prices(prices)
    assert len(returns) == 4
    assert returns[0] == pytest.approx(0.1)
    assert max_drawdown(prices) == pytest.approx((90 / 120) - 1)
    assert max_drawdown([]) is None


def test_var_and_cvar_are_positive_loss_fractions():
    returns = [0.01, -0.02, 0.03, -0.05, 0.0, -0.01, 0.02, -0.04, 0.01, 0.0]
    var = value_at_risk(returns, 0.9)
    cvar = conditional_value_at_risk(returns, 0.9)
    assert var >= 0
    assert cvar >= var
    with pytest.raises(ValueError):
        value_at_risk(returns, 1.5)


def test_sharpe_none_for_flat_series():
    assert sharpe_ratio([0.0, 0.0, 0.0]) is None
    assert sharpe_ratio([0.01, 0.02, 0.015]) > 0


def test_risk_summary_includes_beta_when_benchmark_supplied():
    prices = [100 * (1.01 ** i) for i in range(30)]
    benchmark = [50 * (1.005 ** i) for i in range(30)]
    summary = risk_summary(prices, benchmark_prices=benchmark)
    assert summary.observations == 30
    assert summary.total_return > 0
    assert summary.max_drawdown == 0.0
    assert summary.beta is not None
    assert isinstance(summary.as_dict(), dict)


def test_inverse_volatility_weights_respect_cap():
    calm = [100 + math.sin(i / 3) for i in range(40)]
    wild = [100 + 10 * math.sin(i / 2) for i in range(40)]
    weights = inverse_volatility_weights({"A": calm, "B": wild}, max_weight=0.4)
    assert weights.weights["A"] == 0.4
    assert weights.weights["B"] < weights.weights["A"]
    assert any("cash reserve" in note for note in weights.notes)


def test_correlation_and_concentration():
    wave = [100 + 5 * math.sin(i / 2) for i in range(40)]
    inverse = [100 - 5 * math.sin(i / 2) for i in range(40)]
    matrix = correlation_matrix({"A": wave, "B": wave, "C": inverse})
    assert matrix["A"]["B"] == pytest.approx(1.0)
    assert matrix["A"]["C"] < -0.9
    concentration = concentration_report({"A": 0.6, "B": 0.4})
    assert concentration["largest_ticker"] == "A"
    assert concentration["effective_positions"] < 2


def test_diversification_flags_oversized_and_correlated():
    series = [100 + math.sin(i / 2) * 5 for i in range(30)]
    inverse = [100 - math.sin(i / 2) * 5 for i in range(30)]
    suggestion = suggest_diversification(
        {"A": 0.5, "B": 0.5},
        {"A": series, "B": series},
        max_single_weight=0.25,
        candidate_pool={"C": inverse},
    )
    text = " ".join(suggestion.suggestions)
    assert "초과" in text
    assert suggestion.highly_correlated_pairs[0]["correlation"] == pytest.approx(1.0)
    assert "C" in text
