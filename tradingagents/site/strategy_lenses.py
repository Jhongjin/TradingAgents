"""Deterministic Korean-market lenses for public stock pages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from statistics import mean, stdev
from typing import Any, Iterable


@dataclass(frozen=True)
class StrategyLens:
    id: str
    title: str
    status: str
    score: float | None
    summary: str
    metrics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_korean_strategy_lenses(
    *,
    chart: dict[str, Any],
    analysis: dict[str, Any],
    analysis_refresh: dict[str, Any],
    market: str,
) -> list[dict[str, Any]]:
    """Build lightweight explainability lenses for a Korean stock page.

    These are intentionally deterministic and data-only. They complement the
    expensive LLM reports by exposing the simple checks a user would naturally
    expect before reading a deeper AI thesis.
    """

    points = _numeric_points(chart)
    lenses = [
        _trend_lens(points),
        _momentum_lens(points),
        _liquidity_lens(points),
        _risk_lens(points, market=market),
        _analysis_freshness_lens(analysis, analysis_refresh),
        _safety_lens(),
    ]
    return [lens.as_dict() for lens in lenses]


def _numeric_points(chart: dict[str, Any]) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    if chart.get("status") != "available":
        return rows
    for point in chart.get("points") or []:
        close = _float(point.get("close"))
        if close is None:
            continue
        open_ = _float(point.get("open")) or close
        high = _float(point.get("high")) or close
        low = _float(point.get("low")) or close
        volume = _float(point.get("volume")) or 0.0
        rows.append(
            {
                "date": str(point.get("date") or ""),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    return rows


def _trend_lens(points: list[dict[str, float | str]]) -> StrategyLens:
    if len(points) < 20:
        return _unavailable("trend", "추세", "20거래일 이상 차트 데이터가 필요합니다.")

    closes = _series(points, "close")
    latest = closes[-1]
    ma5 = _average(closes[-5:])
    ma20 = _average(closes[-20:])
    ma60 = _average(closes[-60:]) if len(closes) >= 60 else None
    score = 0.0
    if latest > ma20:
        score += 1.0
    else:
        score -= 1.0
    if ma5 > ma20:
        score += 0.8
    else:
        score -= 0.8
    if ma60 is not None:
        score += 0.6 if latest > ma60 else -0.6

    status = _status_from_score(score, positive=1.0, caution=-1.0)
    if status == "positive":
        summary = "단기 가격이 20일 평균 위에서 움직이며 추세 우위가 확인됩니다."
    elif status == "caution":
        summary = "단기 가격과 평균선 배열이 약해 추세 확인이 더 필요합니다."
    else:
        summary = "평균선 기준 추세는 아직 뚜렷한 한쪽 우위가 아닙니다."
    return StrategyLens(
        id="trend",
        title="추세",
        status=status,
        score=round(score, 2),
        summary=summary,
        metrics={"close": latest, "ma5": round(ma5, 2), "ma20": round(ma20, 2), "ma60": _round(ma60)},
    )


def _momentum_lens(points: list[dict[str, float | str]]) -> StrategyLens:
    if len(points) < 21:
        return _unavailable("momentum", "모멘텀", "20거래일 수익률 계산을 위한 데이터가 필요합니다.")

    closes = _series(points, "close")
    return_20d = _return(closes[-21], closes[-1])
    return_60d = _return(closes[-61], closes[-1]) if len(closes) >= 61 else None
    score = return_20d
    if return_60d is not None:
        score = (return_20d * 0.65) + (return_60d * 0.35)

    status = _status_from_score(score, positive=0.05, caution=-0.05)
    if status == "positive":
        summary = "최근 수익률이 우호적이라 단기 모멘텀은 살아 있습니다."
    elif status == "caution":
        summary = "최근 수익률이 약해 반등 확인 전까지 보수적 접근이 필요합니다."
    else:
        summary = "최근 수익률은 중립권으로, 가격 확인이 더 필요합니다."
    return StrategyLens(
        id="momentum",
        title="모멘텀",
        status=status,
        score=round(score, 4),
        summary=summary,
        metrics={"return_20d": round(return_20d, 4), "return_60d": _round(return_60d, 4)},
    )


def _liquidity_lens(points: list[dict[str, float | str]]) -> StrategyLens:
    if len(points) < 20:
        return _unavailable("liquidity", "수급/거래량", "20거래일 평균 거래량 계산을 위한 데이터가 필요합니다.")

    volumes = _series(points, "volume")
    latest = volumes[-1]
    avg20 = max(_average(volumes[-20:]), 1.0)
    ratio = latest / avg20
    if ratio >= 1.35:
        status = "positive"
        summary = "최근 거래량이 20일 평균을 웃돌아 시장 관심이 증가했습니다."
    elif ratio <= 0.55:
        status = "caution"
        summary = "최근 거래량이 평균보다 낮아 신호 신뢰도를 보수적으로 봐야 합니다."
    else:
        status = "neutral"
        summary = "거래량은 평균권으로, 과열이나 소외 신호는 제한적입니다."
    return StrategyLens(
        id="liquidity",
        title="수급/거래량",
        status=status,
        score=round(ratio, 3),
        summary=summary,
        metrics={"latest_volume": int(latest), "avg20_volume": round(avg20, 2), "volume_ratio": round(ratio, 3)},
    )


def _risk_lens(points: list[dict[str, float | str]], *, market: str) -> StrategyLens:
    if len(points) < 20:
        return _unavailable("risk", "변동성 리스크", "20거래일 변동성 계산을 위한 데이터가 필요합니다.")

    closes = _series(points, "close")
    window = closes[-60:] if len(closes) >= 60 else closes
    high = max(window)
    drawdown = (closes[-1] / high) - 1 if high else 0.0
    daily_returns = [_return(previous, current) for previous, current in zip(closes[-21:-1], closes[-20:]) if previous]
    volatility = stdev(daily_returns) * sqrt(252) if len(daily_returns) >= 2 else 0.0
    is_kosdaq = market.upper() == "KOSDAQ"
    caution_volatility = 0.48 if is_kosdaq else 0.40
    if drawdown <= -0.18 or volatility >= caution_volatility:
        status = "caution"
        summary = "최근 낙폭 또는 변동성이 커서 포지션 크기 제한이 우선입니다."
    elif drawdown > -0.07 and volatility < caution_volatility * 0.7:
        status = "positive"
        summary = "최근 낙폭과 변동성이 관리 가능한 범위에 있습니다."
    else:
        status = "neutral"
        summary = "변동성 리스크는 중간 수준으로, 손절 기준을 명확히 둬야 합니다."
    return StrategyLens(
        id="risk",
        title="변동성 리스크",
        status=status,
        score=round((drawdown * -1) + volatility, 4),
        summary=summary,
        metrics={"drawdown_from_window_high": round(drawdown, 4), "annualized_volatility_20d": round(volatility, 4)},
    )


def _analysis_freshness_lens(analysis: dict[str, Any], analysis_refresh: dict[str, Any]) -> StrategyLens:
    status = str(analysis.get("status") or "missing")
    if status == "available" and not analysis_refresh.get("recommended"):
        label = "positive"
        summary = "저장된 공개 AI 분석이 최신 범위 안에 있습니다."
    elif analysis_refresh.get("recommended"):
        label = "caution"
        summary = "공개 AI 분석 업데이트가 권장됩니다."
    elif status == "not_configured":
        label = "neutral"
        summary = "분석 저장소가 연결되면 공개 리포트 신선도를 추적합니다."
    else:
        label = "neutral"
        summary = "공개 AI 분석이 아직 충분히 축적되지 않았습니다."
    return StrategyLens(
        id="analysis_freshness",
        title="AI 분석 신선도",
        status=label,
        score=None,
        summary=summary,
        metrics={
            "analysis_status": status,
            "refresh_reason": analysis_refresh.get("reason"),
            "age_days": analysis_refresh.get("age_days"),
        },
    )


def _safety_lens() -> StrategyLens:
    return StrategyLens(
        id="safety",
        title="안전 가드레일",
        status="positive",
        score=None,
        summary="실거래 주문은 차단되어 있고, 분석과 수동 기록 중심으로 동작합니다.",
        metrics={"live_trading": "disabled", "broker_orders": "not_supported"},
    )


def _series(points: Iterable[dict[str, float | str]], key: str) -> list[float]:
    return [float(point[key]) for point in points]


def _average(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _return(start: float, end: float) -> float:
    if start == 0:
        return 0.0
    return (end / start) - 1


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _status_from_score(score: float, *, positive: float, caution: float) -> str:
    if score >= positive:
        return "positive"
    if score <= caution:
        return "caution"
    return "neutral"


def _unavailable(lens_id: str, title: str, summary: str) -> StrategyLens:
    return StrategyLens(
        id=lens_id,
        title=title,
        status="unavailable",
        score=None,
        summary=summary,
        metrics={},
    )
