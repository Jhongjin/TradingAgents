"""Read-only screener and forecast payload builders for the public API."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradingagents.analytics import risk_summary
from tradingagents.dataflows.chart_data import get_ohlcv_chart_series
from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker
from tradingagents.forecast import forecast_from_points
from tradingagents.screener import ScreenerConfig, compute_factor_scores, screen_korean_market

from .public_api import _json_ready


SCREENER_NOTICES = [
    "스크리너 결과는 규칙 기반 요인 점수로 정렬한 후보 목록이며 매수 추천이나 투자 조언이 아닙니다.",
    "후보는 AI 분석과 리스크 게이트를 통과해야 가상매매 대상이 되며, 실제 주문과 연결되지 않습니다.",
]

FORECAST_NOTICES = [
    "가격 예측은 통계 모델(TimesFM 또는 드리프트/변동성 모델)의 확률적 추정치이며 미래 수익을 보장하지 않습니다.",
    "예측 구간은 과거 변동성에 기반하며 급격한 뉴스/이벤트 위험을 반영하지 못할 수 있습니다.",
]

MAX_SCREENER_TOP_N = 50
MAX_FORECAST_HORIZON = 60


def build_screener_payload(
    *,
    as_of_date: str | None = None,
    markets: str | None = None,
    top_n: int = 20,
    min_market_cap: float | None = None,
    max_per: float | None = None,
    screener_runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-ready ranked candidate list for KOSPI/KOSDAQ."""

    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if top_n > MAX_SCREENER_TOP_N:
        raise ValueError(f"top_n cannot exceed {MAX_SCREENER_TOP_N}")
    selected_markets = tuple(part.strip().upper() for part in (markets or "KOSPI,KOSDAQ").split(",") if part.strip())
    overrides: dict[str, Any] = {"markets": selected_markets, "top_n": top_n}
    if min_market_cap is not None:
        overrides["min_market_cap"] = float(min_market_cap)
    if max_per is not None:
        overrides["max_per"] = float(max_per)
    config = ScreenerConfig(**overrides)
    runner = screener_runner or screen_korean_market
    result = runner(as_of_date, config=config)
    payload = result.as_dict()
    payload["status"] = "available" if result.candidates else "empty"
    payload["mode"] = "screener"
    payload["notices"] = SCREENER_NOTICES
    payload["generated_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    return _json_ready(payload)


def build_forecast_payload(
    ticker: str,
    *,
    as_of_date: str | None = None,
    horizon_days: int = 20,
    backend: str | None = None,
    chart_vendor: str | None = None,
    history_fetcher: Callable[[str, str, str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build a JSON-ready statistical forecast plus factor and risk context."""

    if not is_kr_ticker(ticker):
        raise ValueError("가격 예측은 6자리 한국 종목코드만 지원합니다.")
    if not 1 <= horizon_days <= MAX_FORECAST_HORIZON:
        raise ValueError(f"horizon_days must be between 1 and {MAX_FORECAST_HORIZON}")
    resolved = resolve_kr_ticker(ticker, lookup_pykrx=False)
    end = _coerce_date(as_of_date) if as_of_date else datetime.now(ZoneInfo("Asia/Seoul")).date()
    start = end - timedelta(days=400)
    fetcher = history_fetcher or _default_history_fetcher(chart_vendor)
    points = list(fetcher(resolved.code, start.isoformat(), end.isoformat()))
    closes = [float(point["close"]) for point in points if point.get("close") is not None]
    base = {
        "mode": "forecast",
        "ticker": {"code": resolved.code, "name": resolved.name, "market": resolved.market, "currency": "KRW"},
        "as_of_date": end,
        "horizon_days": horizon_days,
        "notices": FORECAST_NOTICES,
        "execution_boundary": "forecast_only_no_orders",
    }
    if len(closes) < 2:
        return _json_ready({**base, "status": "insufficient_price_data", "point_count": len(points)})
    forecast = forecast_from_points(points, horizon=horizon_days, backend=backend)
    return _json_ready(
        {
            **base,
            "status": "available",
            "point_count": len(points),
            "last_date": points[-1].get("date"),
            "forecast": forecast.as_dict(),
            "summary": forecast.summary_ko(),
            "factors": compute_factor_scores(points).as_dict(),
            "risk_metrics": risk_summary(closes).as_dict(),
        }
    )


def _default_history_fetcher(chart_vendor: str | None):
    def fetch(code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        series = get_ohlcv_chart_series(code, start_date, end_date, vendor=chart_vendor or "pykrx")
        return [point.as_dict() for point in series.points]

    return fetch


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()
