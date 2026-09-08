"""TimesFM (google-research/timesfm) backend.

Installation (optional, heavy):

    pip install "timesfm[torch]"

The 2.5 checkpoint (``google/timesfm-2.5-200m-pytorch``) is Apache-2.0; the
3.0 checkpoint is released under a non-commercial licence, so the default here
stays on 2.5. Both the 2.5 API (``TimesFM_2p5_200M_torch`` + ``ForecastConfig``)
and the 3.0 API (``timesfm3.TimesFM3Evaluator``) are supported; whichever
import succeeds first is used.
"""

from __future__ import annotations

import os
from importlib import import_module
from typing import Any, Sequence

from .base import DEFAULT_QUANTILES, ForecastResult


DEFAULT_CHECKPOINT = "google/timesfm-2.5-200m-pytorch"
DEFAULT_CONTEXT = 512
DEFAULT_MAX_CONTEXT = 1024
DEFAULT_MAX_HORIZON = 256
_TIMESFM_QUANTILE_LEVELS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def timesfm_available() -> bool:
    for module_name in ("timesfm", "timesfm3"):
        try:
            import_module(module_name)
            return True
        except Exception:
            continue
    return False


class TimesFMForecaster:
    """Univariate close-price forecaster backed by TimesFM.

    The model is loaded lazily on the first ``forecast`` call so constructing
    the object is cheap and import errors surface as a clear ``RuntimeError``
    with install instructions instead of a stack trace deep inside torch.
    """

    name = "timesfm"

    def __init__(
        self,
        *,
        checkpoint: str | None = None,
        device: str | None = None,
        context_length: int | None = None,
        max_context: int = DEFAULT_MAX_CONTEXT,
        max_horizon: int = DEFAULT_MAX_HORIZON,
        model: Any | None = None,
    ):
        self.checkpoint = checkpoint or os.getenv("TRADINGAGENTS_TIMESFM_CHECKPOINT") or DEFAULT_CHECKPOINT
        self.device = device or os.getenv("TRADINGAGENTS_TIMESFM_DEVICE") or "cpu"
        self.context_length = int(context_length or os.getenv("TRADINGAGENTS_TIMESFM_CONTEXT") or DEFAULT_CONTEXT)
        self.max_context = max_context
        self.max_horizon = max_horizon
        self._model = model
        self._api: str | None = "injected" if model is not None else None

    # ------------------------------------------------------------------ loading
    def _load(self) -> None:
        if self._model is not None:
            return
        errors: list[str] = []
        try:
            timesfm = import_module("timesfm")
            model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(self.checkpoint)
            model.compile(
                timesfm.ForecastConfig(
                    max_context=self.max_context,
                    max_horizon=self.max_horizon,
                    normalize_inputs=True,
                    use_continuous_quantile_head=True,
                    force_flip_invariance=True,
                    infer_is_positive=True,
                    fix_quantile_crossing=True,
                )
            )
            self._model = model
            self._api = "timesfm_2p5"
            return
        except Exception as exc:  # pragma: no cover - depends on optional install
            errors.append(f"timesfm 2.5 API: {exc.__class__.__name__}: {exc}")
        try:  # pragma: no cover - depends on optional install
            timesfm3 = import_module("timesfm3")
            config = timesfm3.ModelConfig(checkpoint_path=self.checkpoint, per_core_batch_size=1, device=self.device)
            self._model = timesfm3.TimesFM3Evaluator(config)
            self._api = "timesfm_3"
            return
        except Exception as exc:  # pragma: no cover
            errors.append(f"timesfm 3.0 API: {exc.__class__.__name__}: {exc}")
        raise RuntimeError(
            "TimesFM is not available. Install with `pip install \"timesfm[torch]\"` "
            "or set TRADINGAGENTS_FORECAST_BACKEND=naive. Details: " + " | ".join(errors)
        )

    # --------------------------------------------------------------- forecasting
    def forecast(self, closes: Sequence[float], *, horizon: int = 20) -> ForecastResult:
        if horizon <= 0:
            raise ValueError("horizon must be positive")
        if horizon > self.max_horizon:
            raise ValueError(f"horizon {horizon} exceeds max_horizon {self.max_horizon}")
        cleaned = [float(value) for value in closes if value is not None and float(value) > 0]
        if len(cleaned) < 2:
            raise ValueError("at least two positive close prices are required")
        context = cleaned[-self.context_length :]
        self._load()
        point_forecast, quantile_forecast = self._run_model(context, horizon)

        median_path = [round(float(value), 4) for value in point_forecast[:horizon]]
        quantile_paths: dict[str, list[float]] = {}
        if quantile_forecast is not None:
            for quantile in DEFAULT_QUANTILES:
                column = _quantile_column(quantile_forecast, quantile)
                if column is not None:
                    quantile_paths[str(quantile)] = [round(float(value), 4) for value in column[:horizon]]
        last_close = cleaned[-1]
        expected_return = (median_path[-1] / last_close) - 1 if median_path else None
        probability_up = _probability_up(quantile_paths, last_close)
        return ForecastResult(
            backend=self.name,
            horizon=horizon,
            last_close=last_close,
            median_path=median_path,
            quantile_paths=quantile_paths,
            expected_return=round(expected_return, 6) if expected_return is not None else None,
            probability_up=probability_up,
            context_length=len(context),
            notes=[f"checkpoint {self.checkpoint}", f"api {self._api}"],
        )

    def _run_model(self, context: Sequence[float], horizon: int) -> tuple[Sequence[float], Any]:
        import numpy as np

        series = np.asarray(context, dtype=np.float32)
        model = self._model
        if self._api == "timesfm_3":  # pragma: no cover - optional install
            outputs = list(model.predict_batch([series], horizon=horizon, return_quantiles=True))
            first = outputs[0]
            point = np.asarray(first[0] if isinstance(first, (tuple, list)) else first).reshape(-1)
            quantiles = np.asarray(first[1]) if isinstance(first, (tuple, list)) and len(first) > 1 else None
            return point, quantiles
        point_batch, quantile_batch = model.forecast(horizon=horizon, inputs=[series])
        point = np.asarray(point_batch[0]).reshape(-1)
        quantiles = np.asarray(quantile_batch[0]) if quantile_batch is not None else None
        return point, quantiles


def _quantile_column(quantiles: Any, quantile: float) -> Sequence[float] | None:
    """Map a requested quantile onto TimesFM's ``(horizon, 10)`` quantile block.

    TimesFM returns the mean in column 0 followed by the 0.1..0.9 quantiles.
    Injected/mock models may return exactly nine quantile columns instead.
    """

    import numpy as np

    array = np.asarray(quantiles)
    if array.ndim != 2:
        return None
    columns = array.shape[1]
    if columns == len(_TIMESFM_QUANTILE_LEVELS) + 1:
        offset = 1
    elif columns == len(_TIMESFM_QUANTILE_LEVELS):
        offset = 0
    else:
        return None
    nearest = min(range(len(_TIMESFM_QUANTILE_LEVELS)), key=lambda index: abs(_TIMESFM_QUANTILE_LEVELS[index] - quantile))
    return array[:, offset + nearest]


def _probability_up(quantile_paths: dict[str, list[float]], last_close: float) -> float | None:
    """Estimate P(final close > last close) by interpolating the quantile ladder."""

    levels = []
    for key, path in quantile_paths.items():
        if path:
            levels.append((float(key), path[-1]))
    if len(levels) < 2:
        return None
    levels.sort()
    if last_close <= levels[0][1]:
        return round(1 - levels[0][0], 4)
    if last_close >= levels[-1][1]:
        return round(1 - levels[-1][0], 4)
    for (low_q, low_v), (high_q, high_v) in zip(levels[:-1], levels[1:]):
        if low_v <= last_close <= high_v:
            if high_v == low_v:
                return round(1 - low_q, 4)
            fraction = (last_close - low_v) / (high_v - low_v)
            return round(1 - (low_q + fraction * (high_q - low_q)), 4)
    return None
