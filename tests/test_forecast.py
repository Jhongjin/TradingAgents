import numpy as np
import pytest

from tradingagents.forecast import (
    NaiveForecaster,
    TimesFMForecaster,
    forecast_from_points,
    get_forecaster,
    timesfm_available,
)
from tradingagents.forecast.timesfm_backend import _probability_up, _quantile_column


def _closes(count=120, drift=0.003):
    close = 10_000.0
    values = []
    for _ in range(count):
        close *= 1 + drift
        values.append(close)
    return values


def test_naive_forecaster_produces_monotone_quantiles_and_probability():
    result = NaiveForecaster().forecast(_closes(), horizon=10)

    assert result.backend == "naive"
    assert result.horizon == 10
    assert len(result.median_path) == 10
    assert set(result.quantile_paths) == {"0.1", "0.25", "0.5", "0.75", "0.9"}
    assert result.quantile_paths["0.1"][-1] <= result.median_path[-1] <= result.quantile_paths["0.9"][-1]
    assert result.expected_return > 0
    assert 0.5 <= result.probability_up <= 1.0
    assert result.target_close == result.median_path[-1]
    assert "naive" in result.summary_ko()


def test_naive_forecaster_validates_inputs():
    with pytest.raises(ValueError):
        NaiveForecaster().forecast([100.0], horizon=5)
    with pytest.raises(ValueError):
        NaiveForecaster().forecast(_closes(), horizon=0)
    short = NaiveForecaster().forecast(_closes(5), horizon=3)
    assert short.notes


def test_forecast_from_points_uses_close_field_and_backend_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_FORECAST_BACKEND", "naive")
    points = [{"date": str(i), "close": value} for i, value in enumerate(_closes(60))]
    result = forecast_from_points(points, horizon=5)
    assert result.context_length == 60
    assert result.horizon == 5


def test_get_forecaster_auto_falls_back_without_timesfm(monkeypatch):
    monkeypatch.setattr("tradingagents.forecast.timesfm_backend.timesfm_available", lambda: False)
    assert isinstance(get_forecaster("auto"), NaiveForecaster)
    with pytest.raises(ValueError):
        get_forecaster("prophet")


def test_timesfm_forecaster_uses_injected_model_without_torch():
    class FakeModel:
        def forecast(self, *, horizon, inputs):
            last = float(inputs[0][-1])
            point = np.array([[last * (1 + 0.01 * step) for step in range(1, horizon + 1)]])
            levels = np.linspace(0.9, 1.1, 9)
            quantiles = np.array([[[value * level for level in np.concatenate(([1.0], levels))] for value in point[0]]])
            return point, quantiles

    forecaster = TimesFMForecaster(model=FakeModel(), context_length=50)
    result = forecaster.forecast(_closes(80), horizon=4)

    assert result.backend == "timesfm"
    assert result.context_length == 50
    assert len(result.median_path) == 4
    assert result.quantile_paths["0.1"][-1] < result.median_path[-1] < result.quantile_paths["0.9"][-1]
    assert result.expected_return == pytest.approx(0.04, rel=1e-3)
    assert result.probability_up is not None
    assert any("api injected" in note for note in result.notes)


def test_timesfm_forecaster_reports_missing_dependency(monkeypatch):
    monkeypatch.setattr("tradingagents.forecast.timesfm_backend.import_module", lambda name: (_ for _ in ()).throw(ImportError(name)))
    forecaster = TimesFMForecaster()
    with pytest.raises(RuntimeError, match="TimesFM is not available"):
        forecaster.forecast(_closes(), horizon=3)
    assert timesfm_available() in {True, False}


def test_quantile_column_and_probability_helpers():
    block = np.array([[0.0, 1, 2, 3, 4, 5, 6, 7, 8, 9]])
    assert _quantile_column(block, 0.5)[0] == 5
    nine = np.array([[1, 2, 3, 4, 5, 6, 7, 8, 9]])
    assert _quantile_column(nine, 0.9)[0] == 9
    assert _quantile_column(np.array([[1, 2, 3]]), 0.5) is None
    paths = {"0.1": [90.0], "0.5": [100.0], "0.9": [110.0]}
    assert _probability_up(paths, 100.0) == pytest.approx(0.5)
    assert _probability_up(paths, 80.0) == pytest.approx(0.9)
    assert _probability_up(paths, 120.0) == pytest.approx(0.1)
