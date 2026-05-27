"""Public paper-simulation preview payloads."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.chart_data import get_ohlcv_chart_series
from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker
from tradingagents.execution import PaperSimulationConfig, TradeSignal, SignalPolicy, simulate_single_position
from tradingagents.storage import StorageRepository

from .public_api import _json_ready


SIMULATION_NOTICES = [
    "모의투자 결과는 일봉 종가 기준 가상 체결이며 실제 주문이나 투자 조언이 아닙니다.",
    "청산은 기본 익절, 손절, 보유일 규칙으로 계산되며 브로커 주문과 연결되지 않습니다.",
]


def build_public_simulation_preview_payload(
    repo: StorageRepository | None,
    *,
    ticker: str,
    as_of_date: str | None = None,
    chart_vendor: str | None = None,
    initial_cash: float = 10_000_000.0,
    take_profit_pct: float = 0.08,
    stop_loss_pct: float = 0.05,
    max_holding_days: int = 20,
    slippage_bps: float = 3.0,
) -> dict[str, Any]:
    """Build a read-only paper-trade preview from the latest public analysis."""

    if not is_kr_ticker(ticker):
        raise ValueError("simulation preview currently supports Korean 6-digit tickers only")
    resolved = resolve_kr_ticker(ticker, lookup_pykrx=False)
    if repo is None:
        return _json_ready(
            {
                "status": "not_configured",
                "ticker": _ticker_payload(resolved),
                "notices": SIMULATION_NOTICES,
            }
        )

    bundle = repo.latest_public_analysis_bundle(resolved.code)
    if bundle is None:
        return _json_ready(
            {
                "status": "no_completed_analysis",
                "ticker": _ticker_payload(resolved),
                "notices": SIMULATION_NOTICES,
            }
        )

    run = bundle.get("run") or {}
    decision = bundle.get("decision")
    if not decision:
        return _json_ready(
            {
                "status": "no_decision",
                "ticker": _ticker_payload(resolved),
                "analysis_run_id": run.get("id"),
                "notices": SIMULATION_NOTICES,
            }
        )

    trade_date = _coerce_date(run.get("trade_date"))
    end_date = _coerce_date(as_of_date) if as_of_date else datetime.now(ZoneInfo("Asia/Seoul")).date()
    if end_date < trade_date:
        raise ValueError("as_of_date must be on or after the analysis trade_date")

    series = get_ohlcv_chart_series(
        resolved.code,
        trade_date.isoformat(),
        end_date.isoformat(),
        vendor=chart_vendor or "pykrx",
    )
    if len(series.points) < 2:
        return _json_ready(
            {
                "status": "insufficient_price_data",
                "ticker": _ticker_payload(resolved),
                "analysis_run_id": run.get("id"),
                "trade_date": trade_date,
                "point_count": len(series.points),
                "notices": SIMULATION_NOTICES,
            }
        )

    signal = _signal_from_decision(resolved.code, decision)
    config = PaperSimulationConfig(
        initial_cash=initial_cash,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        max_holding_days=max_holding_days,
        max_position_weight=0.25,
        slippage_bps=slippage_bps,
        currency="KRW",
    )
    simulation = simulate_single_position(signal, [point.as_dict() for point in series.points], config=config)
    return _json_ready(
        {
            "status": "available",
            "mode": "paper_simulation",
            "execution_boundary": "simulation_only_no_orders",
            "ticker": _ticker_payload(resolved),
            "analysis_run_id": run.get("id"),
            "trade_date": trade_date,
            "as_of_date": end_date,
            "chart_vendor": series.vendor,
            "point_count": len(series.points),
            "assumptions": {
                "initial_cash": initial_cash,
                "take_profit_pct": take_profit_pct,
                "stop_loss_pct": stop_loss_pct,
                "max_holding_days": max_holding_days,
                "max_position_weight": config.max_position_weight,
                "slippage_bps": slippage_bps,
                "price_basis": "daily_close",
            },
            "decision": {
                "rating": decision.get("rating"),
                "action": decision.get("action"),
                "target_weight": signal.target_weight,
            },
            "simulation": simulation.as_dict(),
            "notices": SIMULATION_NOTICES,
        }
    )


def _signal_from_decision(ticker_code: str, decision: dict[str, Any]) -> TradeSignal:
    rating = str(decision.get("rating") or "")
    target_weight = decision.get("target_weight")
    if target_weight is None:
        target_weight = SignalPolicy().target_for_rating(rating)
    else:
        target_weight = float(target_weight)
    return TradeSignal(
        ticker=ticker_code,
        rating=rating,
        action=str(decision.get("action") or ""),
        target_weight=target_weight,
        rationale=str(decision.get("rationale") or decision.get("raw_decision") or ""),
    )


def _ticker_payload(resolved) -> dict[str, str]:
    return {
        "code": resolved.code,
        "name": resolved.name,
        "market": resolved.market,
        "currency": "KRW",
    }


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()
