"""Evaluate stored public analysis runs against later Korean-market returns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from tradingagents.dataflows.kr_returns import fetch_korean_returns
from tradingagents.dataflows.kr_tickers import resolve_kr_ticker
from tradingagents.storage import AnalysisOutcomeInput, StorageRepository


DEFAULT_OUTCOME_HORIZONS = (5, 20)


@dataclass(frozen=True)
class AnalysisOutcomeResult:
    analysis_run_id: str
    ticker_code: str
    horizon_days: int
    status: str
    actual_holding_days: int | None = None
    raw_return: float | None = None
    benchmark_return: float | None = None
    alpha_return: float | None = None
    error: str | None = None


def evaluate_public_analysis_outcomes(
    repo: StorageRepository,
    *,
    horizons: Iterable[int] = DEFAULT_OUTCOME_HORIZONS,
    limit: int = 20,
    as_of_date: str | date | None = None,
) -> list[AnalysisOutcomeResult]:
    """Compute and upsert outcome rows for recent completed public analyses."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    horizon_values = tuple(int(value) for value in horizons)
    if not horizon_values:
        raise ValueError("at least one horizon is required")
    if any(value <= 0 for value in horizon_values):
        raise ValueError("horizons must be positive")

    evaluated_at = _coerce_date(as_of_date) if as_of_date is not None else datetime.now(ZoneInfo("Asia/Seoul")).date()
    results: list[AnalysisOutcomeResult] = []
    for run in repo.list_public_analysis_runs(limit=limit):
        bundle = repo.get_analysis_bundle(str(run["id"])) or {}
        decision = bundle.get("decision") or {}
        ticker_code = str(run["ticker_code"])
        ticker_name = run.get("ticker_name")
        market = str(run.get("market") or "KR")
        trade_date = _coerce_date(run["trade_date"])
        benchmark_symbol = _benchmark_symbol(ticker_code)

        for horizon in horizon_values:
            existing = _existing_outcome_for_horizon(bundle.get("outcomes") or [], horizon)
            if existing is not None and existing.get("status") == "completed":
                results.append(_skipped_completed_result(run, existing))
                continue
            result = _evaluate_one(
                repo,
                analysis_run_id=str(run["id"]),
                ticker_code=ticker_code,
                ticker_name=str(ticker_name) if ticker_name else None,
                market=market,
                trade_date=trade_date,
                evaluated_at=evaluated_at,
                horizon_days=horizon,
                benchmark_symbol=benchmark_symbol,
                decision=decision,
            )
            results.append(result)
    return results


def _existing_outcome_for_horizon(outcomes: list[dict], horizon_days: int) -> dict | None:
    for outcome in outcomes:
        if int(outcome.get("horizon_days") or 0) == horizon_days:
            return outcome
    return None


def _skipped_completed_result(run: dict, outcome: dict) -> AnalysisOutcomeResult:
    return AnalysisOutcomeResult(
        analysis_run_id=str(run["id"]),
        ticker_code=str(run["ticker_code"]),
        horizon_days=int(outcome["horizon_days"]),
        status="skipped",
        actual_holding_days=outcome.get("actual_holding_days"),
        raw_return=outcome.get("raw_return"),
        benchmark_return=outcome.get("benchmark_return"),
        alpha_return=outcome.get("alpha_return"),
        error="already_completed",
    )


def _evaluate_one(
    repo: StorageRepository,
    *,
    analysis_run_id: str,
    ticker_code: str,
    ticker_name: str | None,
    market: str,
    trade_date: date,
    evaluated_at: date,
    horizon_days: int,
    benchmark_symbol: str | None,
    decision: dict,
) -> AnalysisOutcomeResult:
    raw_return = None
    benchmark_return = None
    alpha_return = None
    actual_holding_days = None
    status = "unavailable"
    error = None

    try:
        raw, alpha, actual_days = fetch_korean_returns(ticker_code, trade_date.isoformat(), horizon_days)
        actual_holding_days = actual_days
        if raw is None or alpha is None or actual_days is None:
            error = "return_data_unavailable"
        elif actual_days < horizon_days:
            status = "pending"
            error = "insufficient_holding_days"
        else:
            raw_return = raw
            alpha_return = alpha
            benchmark_return = raw - alpha
            status = "completed"
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"

    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=analysis_run_id,
            ticker_code=ticker_code,
            ticker_name=ticker_name,
            market=market,
            trade_date=trade_date,
            evaluated_at=evaluated_at,
            horizon_days=horizon_days,
            actual_holding_days=actual_holding_days,
            benchmark_symbol=benchmark_symbol,
            raw_return=raw_return,
            benchmark_return=benchmark_return,
            alpha_return=alpha_return,
            decision_rating=decision.get("rating"),
            decision_action=decision.get("action"),
            status=status,
            error=error,
            metadata={"source": "outcome_worker"},
        )
    )
    return AnalysisOutcomeResult(
        analysis_run_id=analysis_run_id,
        ticker_code=ticker_code,
        horizon_days=horizon_days,
        status=status,
        actual_holding_days=actual_holding_days,
        raw_return=raw_return,
        benchmark_return=benchmark_return,
        alpha_return=alpha_return,
        error=error,
    )


def _coerce_date(value: str | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _benchmark_symbol(ticker_code: str) -> str | None:
    try:
        return resolve_kr_ticker(ticker_code, lookup_pykrx=False).benchmark_symbol
    except Exception:
        return None
