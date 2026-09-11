"""What is forming right now, and what followed it last time.

The lab's study says what happened after each pattern across years of bars.
This puts that record beside the live chart: fetch the latest bars for every
timeframe, find the patterns that completed in the last few of them, and attach
the measured record to each one — how often the price was higher afterwards,
how that compares with any other bar, how far it typically ran, and how far it
first went the other way.

It forecasts by quoting the past, never by asserting the future. Every number
shown is a count of what happened before, with the sample size beside it so a
pattern seen eleven times cannot pass for one seen a thousand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import CONTRACTS, ContractSpec, GOLD_FUTURES
from .data import BarSeries, cache_dir, load_bars
from .patterns import PATTERN_REGISTRY, PatternHit, detect_patterns
from .study import DEFAULT_HORIZONS, run_pattern_study

DEFAULT_INTERVALS = ("5m", "15m", "1h", "4h", "1d")
# A pattern that completed several bars ago is history, not a setup.
DEFAULT_RECENT_BARS = 3
MIN_SAMPLES_FOR_CONFIDENCE = 30


def studies_dir() -> Path:
    path = cache_dir().parent / "studies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def study_path(symbol: str, interval: str) -> Path:
    safe = symbol.replace("=", "_").replace("/", "_")
    return studies_dir() / f"{safe}__{interval}.json"


def save_study(payload: Mapping[str, Any], *, symbol: str, interval: str) -> Path:
    target = study_path(symbol, interval)
    body = dict(payload)
    body["saved_at"] = datetime.now(timezone.utc).isoformat()
    target.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_study(symbol: str, interval: str) -> dict[str, Any] | None:
    source = study_path(symbol, interval)
    if not source.exists():
        return None
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ensure_study(
    symbol: str,
    interval: str,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    refresh: bool = False,
    series: BarSeries | None = None,
) -> dict[str, Any] | None:
    """Read the stored measurement, or take one now if there is none."""

    if not refresh:
        stored = load_study(symbol, interval)
        if stored:
            return stored
    bars = series or load_bars(symbol, interval=interval)
    try:
        result = run_pattern_study(bars, horizons=horizons, contract=CONTRACTS.get(symbol, GOLD_FUTURES))
    except ValueError:
        return None
    payload = result.as_dict()
    save_study(payload, symbol=symbol, interval=interval)
    return payload


@dataclass
class LiveSignal:
    interval: str
    pattern: str
    label: str
    direction: str
    timestamp: str
    bars_ago: int
    price: float
    last_price: float
    horizon: int | None = None
    samples: int = 0
    win_rate: float | None = None
    base_win_rate: float | None = None
    edge_win_rate: float | None = None
    average_return: float | None = None
    t_stat: float | None = None
    upside_price: float | None = None
    downside_price: float | None = None
    expected_price: float | None = None
    money_per_contract: float | None = None
    confidence: str = "표본 부족"

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class LiveScan:
    symbol: str
    generated_at: str
    intervals: list[dict[str, Any]] = field(default_factory=list)
    signals: list[LiveSignal] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "generated_at": self.generated_at,
            "intervals": self.intervals,
            "signals": [signal.as_dict() for signal in self.signals],
            "bias": self.bias(),
            "notes": self.notes,
        }

    def bias(self) -> dict[str, Any]:
        """One line across timeframes, weighted by how well each pattern scored.

        A count of signals would let eleven noisy ones outvote a single measured
        one, so each contributes its edge over the base rate, and only when it
        has the samples to have earned a vote.
        """

        up = down = 0.0
        counted = 0
        for signal in self.signals:
            if signal.samples < MIN_SAMPLES_FOR_CONFIDENCE or signal.edge_win_rate is None:
                continue
            weight = abs(signal.edge_win_rate) * (1 if (signal.t_stat or 0) >= 2 else 0.4)
            counted += 1
            if signal.direction == "bullish":
                up += weight if signal.edge_win_rate > 0 else -weight
            else:
                down += weight if signal.edge_win_rate > 0 else -weight
        total = up + down
        if counted == 0 or total <= 0:
            return {"direction": "판단 보류", "up": round(up, 4), "down": round(down, 4), "counted": counted}
        share = up / total
        if share >= 0.65:
            label = "상승 우세"
        elif share <= 0.35:
            label = "하락 우세"
        else:
            label = "혼재"
        return {"direction": label, "up": round(up, 4), "down": round(down, 4), "counted": counted, "up_share": round(share, 4)}


def _stats_for(study: Mapping[str, Any] | None, pattern: str, horizon: int | None) -> tuple[int | None, dict[str, Any]]:
    """The measured record for one pattern, at the requested or best horizon."""

    if not study:
        return None, {}
    row = next((item for item in study.get("patterns") or [] if item.get("pattern") == pattern), None)
    if not row:
        return None, {}
    horizons = row.get("horizons") or {}
    if horizon is not None and str(horizon) in horizons:
        return horizon, dict(horizons[str(horizon)])
    # otherwise the horizon with the most convincing record
    best_key, best = None, {}
    for key, stats in horizons.items():
        if not stats.get("enough_samples"):
            continue
        if best_key is None or abs(stats.get("t_stat") or 0) > abs(best.get("t_stat") or 0):
            best_key, best = key, dict(stats)
    if best_key is None and horizons:
        best_key = sorted(horizons)[0]
        best = dict(horizons[best_key])
    return (int(best_key) if best_key is not None else None), best


def _confidence(stats: Mapping[str, Any]) -> str:
    samples = int(stats.get("count") or 0)
    t_stat = abs(float(stats.get("t_stat") or 0))
    edge = float(stats.get("edge_win_rate") or 0)
    if samples < MIN_SAMPLES_FOR_CONFIDENCE:
        return "표본 부족"
    if t_stat >= 3 and edge > 0:
        return "강함"
    if t_stat >= 2 and edge > 0:
        return "보통"
    if edge <= 0:
        return "기준 미달"
    return "약함"


def scan_live(
    symbol: str = "GC=F",
    *,
    intervals: Sequence[str] = DEFAULT_INTERVALS,
    recent_bars: int = DEFAULT_RECENT_BARS,
    horizon: int | None = None,
    refresh: bool = True,
    refresh_study: bool = False,
    contract: ContractSpec | None = None,
) -> LiveScan:
    """Fetch every timeframe, find what just completed, attach the record."""

    spec = contract or CONTRACTS.get(symbol, GOLD_FUTURES)
    scan = LiveScan(symbol=symbol, generated_at=datetime.now(timezone.utc).isoformat())

    for interval in intervals:
        try:
            series = load_bars(symbol, interval=interval, refresh=refresh)
        except Exception as exc:
            scan.intervals.append({"interval": interval, "status": "unavailable", "error": f"{exc.__class__.__name__}: {exc}"})
            continue
        if len(series) < 60:
            scan.intervals.append({"interval": interval, "status": "too_short", "bars": len(series)})
            continue

        study = ensure_study(symbol, interval, refresh=refresh_study, series=series)
        last = series.bars[-1]
        scan.intervals.append(
            {
                "interval": interval,
                "status": "available",
                "bars": len(series),
                "last_timestamp": last.timestamp.isoformat(),
                "last_price": last.close,
                "study_bars": (study or {}).get("bars"),
                "study_saved_at": (study or {}).get("saved_at"),
            }
        )

        cutoff = len(series) - 1 - max(recent_bars - 1, 0)
        for hit in detect_patterns(series):
            if hit.index < cutoff:
                continue
            used_horizon, stats = _stats_for(study, hit.pattern, horizon)
            samples = int(stats.get("count") or 0)
            average = stats.get("average_return")
            mfe = stats.get("average_mfe")
            mae = stats.get("average_mae")
            long = hit.direction == "bullish"
            price = last.close

            def _project(move: Any, *, favourable: bool) -> float | None:
                if move is None:
                    return None
                magnitude = abs(float(move))
                if long:
                    return spec.round_to_tick(price * (1 + magnitude) if favourable else price * (1 - magnitude))
                return spec.round_to_tick(price * (1 - magnitude) if favourable else price * (1 + magnitude))

            signal = LiveSignal(
                interval=interval,
                pattern=hit.pattern,
                label=hit.label,
                direction=hit.direction,
                timestamp=hit.timestamp.isoformat(),
                bars_ago=len(series) - 1 - hit.index,
                price=hit.price,
                last_price=price,
                horizon=used_horizon,
                samples=samples,
                win_rate=stats.get("win_rate"),
                base_win_rate=stats.get("base_win_rate"),
                edge_win_rate=stats.get("edge_win_rate"),
                average_return=average,
                t_stat=stats.get("t_stat"),
                upside_price=_project(mfe, favourable=True),
                downside_price=_project(mae, favourable=False),
                expected_price=_project(average, favourable=True) if (average or 0) >= 0 else _project(average, favourable=False),
                money_per_contract=stats.get("money_per_trade"),
                confidence=_confidence(stats),
            )
            scan.signals.append(signal)

    scan.signals.sort(key=lambda item: (item.bars_ago, -(abs(item.t_stat or 0))))
    scan.notes = [
        "승률과 폭은 같은 종목의 과거 같은 패턴에서 측정한 값입니다. 앞으로를 보장하지 않습니다.",
        "'기준 대비'는 같은 구간 아무 봉에서나 진입했을 때와의 차이입니다. 0 근처면 패턴이 시장을 따라간 것입니다.",
        f"표본 {MIN_SAMPLES_FOR_CONFIDENCE}회 미만은 신뢰도를 매기지 않습니다.",
        "예상 상단은 과거 평균 최대 유리폭, 예상 하단은 평균 최대 불리폭입니다.",
    ]
    return scan
