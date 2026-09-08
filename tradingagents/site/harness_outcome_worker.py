"""Evaluate harness picks (stage=ordered) against later Korean-market returns.

Mirrors ``outcome_worker`` for analysis runs: for every public harness
decision that reached the order stage, compute raw return and KOSPI/KOSDAQ
benchmark alpha over 5 and 20 trading days from the as-of date. Rows stay
``pending`` until the horizon has elapsed and ``unavailable`` when market
data is missing, so misses are never silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from tradingagents.dataflows.kr_returns import fetch_korean_returns
from tradingagents.dataflows.kr_tickers import resolve_kr_ticker
from tradingagents.storage import HarnessOutcomeInput, StorageRepository


DEFAULT_HARNESS_OUTCOME_HORIZONS = (5, 20)


@dataclass(frozen=True)
class HarnessOutcomeResult:
    harness_decision_id: str
    harness_run_id: str
    ticker_code: str
    horizon_days: int
    status: str
    actual_holding_days: int | None = None
    raw_return: float | None = None
    benchmark_return: float | None = None
    alpha_return: float | None = None
    error: str | None = None


def evaluate_harness_outcomes(
    repo: StorageRepository,
    *,
    horizons: Iterable[int] = DEFAULT_HARNESS_OUTCOME_HORIZONS,
    limit: int = 50,
    as_of_date: str | date | None = None,
    returns_fetcher=None,
) -> list[HarnessOutcomeResult]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    # Resolve at call time so tests can monkeypatch the module attribute.
    returns_fetcher = returns_fetcher or fetch_korean_returns
    horizon_values = tuple(int(value) for value in horizons)
    if not horizon_values or any(value <= 0 for value in horizon_values):
        raise ValueError("horizons must be positive")
    evaluated_at = _coerce_date(as_of_date) if as_of_date is not None else datetime.now(ZoneInfo("Asia/Seoul")).date()

    results: list[HarnessOutcomeResult] = []
    for decision in repo.list_harness_decisions_for_outcomes(limit=limit):
        decision_id = str(decision["id"])
        run_id = str(decision["harness_run_id"])
        ticker_code = str(decision["ticker_code"])
        entry_date = _coerce_date(decision["as_of_date"])
        existing_by_horizon = {int(row["horizon_days"]): row for row in decision.get("outcomes") or []}
        for horizon in horizon_values:
            existing = existing_by_horizon.get(horizon)
            if existing is not None and existing.get("status") == "completed":
                results.append(
                    HarnessOutcomeResult(
                        harness_decision_id=decision_id,
                        harness_run_id=run_id,
                        ticker_code=ticker_code,
                        horizon_days=horizon,
                        status="skipped",
                        actual_holding_days=existing.get("actual_holding_days"),
                        raw_return=existing.get("raw_return"),
                        benchmark_return=existing.get("benchmark_return"),
                        alpha_return=existing.get("alpha_return"),
                        error="already_completed",
                    )
                )
                continue
            results.append(
                _evaluate_one(
                    repo,
                    decision=decision,
                    entry_date=entry_date,
                    evaluated_at=evaluated_at,
                    horizon_days=horizon,
                    returns_fetcher=returns_fetcher,
                )
            )
    return results


def summarize_harness_outcome_results(results: Iterable[HarnessOutcomeResult]) -> dict[str, Any]:
    rows = list(results)
    status_counts: dict[str, int] = {}
    alpha_values: list[float] = []
    wins = 0
    for result in rows:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        if result.status == "completed" and result.alpha_return is not None:
            alpha_values.append(float(result.alpha_return))
            if result.raw_return is not None and float(result.raw_return) > 0:
                wins += 1
    completed = status_counts.get("completed", 0)
    return {
        "result_count": len(rows),
        "status_counts": status_counts,
        "completed_count": completed,
        "pending_count": status_counts.get("pending", 0),
        "unavailable_count": status_counts.get("unavailable", 0),
        "skipped_count": status_counts.get("skipped", 0),
        "hit_rate": (wins / completed) if completed else None,
        "average_alpha_return": (sum(alpha_values) / len(alpha_values)) if alpha_values else None,
    }


def summarize_stored_harness_outcomes(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate stored outcome rows per horizon for public payloads."""

    per_horizon: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("horizon_days"))
        bucket = per_horizon.setdefault(key, {"completed": 0, "pending": 0, "unavailable": 0, "wins": 0, "alpha_sum": 0.0, "raw_sum": 0.0})
        status = str(row.get("status") or "")
        if status in bucket:
            bucket[status] += 1
        if status == "completed":
            raw = float(row.get("raw_return") or 0.0)
            bucket["raw_sum"] += raw
            bucket["alpha_sum"] += float(row.get("alpha_return") or 0.0)
            if raw > 0:
                bucket["wins"] += 1
    summary: dict[str, Any] = {}
    for key, bucket in sorted(per_horizon.items(), key=lambda item: int(item[0])):
        completed = bucket["completed"]
        summary[key] = {
            "completed": completed,
            "pending": bucket["pending"],
            "unavailable": bucket["unavailable"],
            "hit_rate": round(bucket["wins"] / completed, 4) if completed else None,
            "average_return": round(bucket["raw_sum"] / completed, 6) if completed else None,
            "average_alpha": round(bucket["alpha_sum"] / completed, 6) if completed else None,
        }
    return summary


def _evaluate_one(
    repo: StorageRepository,
    *,
    decision: dict[str, Any],
    entry_date: date,
    evaluated_at: date,
    horizon_days: int,
    returns_fetcher,
) -> HarnessOutcomeResult:
    decision_id = str(decision["id"])
    run_id = str(decision["harness_run_id"])
    ticker_code = str(decision["ticker_code"])
    raw_return = benchmark_return = alpha_return = None
    actual_holding_days = None
    status = "unavailable"
    error = None
    try:
        raw, alpha, actual_days = returns_fetcher(ticker_code, entry_date.isoformat(), horizon_days)
        actual_holding_days = actual_days
        if raw is None or alpha is None or actual_days is None:
            # Fewer than two aligned closes: either the horizon has not started
            # yet (entry today / yesterday) or data is genuinely missing.
            if _horizon_may_still_elapse(entry_date, evaluated_at, horizon_days):
                status = "pending"
                error = "horizon_not_elapsed"
            else:
                error = "return_data_unavailable"
        elif actual_days < horizon_days:
            status = "pending"
            error = "insufficient_holding_days"
        else:
            raw_return, alpha_return = raw, alpha
            benchmark_return = raw - alpha
            status = "completed"
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"

    repo.upsert_harness_outcome(
        HarnessOutcomeInput(
            harness_decision_id=decision_id,
            harness_run_id=run_id,
            ticker_code=ticker_code,
            ticker_name=decision.get("ticker_name"),
            market=str(decision.get("market") or "KR"),
            entry_date=entry_date,
            evaluated_at=evaluated_at,
            horizon_days=horizon_days,
            actual_holding_days=actual_holding_days,
            benchmark_symbol=_benchmark_symbol(ticker_code),
            raw_return=raw_return,
            benchmark_return=benchmark_return,
            alpha_return=alpha_return,
            confirmation_rating=decision.get("confirmation_rating"),
            confirmation_source=decision.get("confirmation_source"),
            status=status,
            error=error,
            metadata={"source": "harness_outcome_worker", "stage": decision.get("stage")},
        )
    )
    return HarnessOutcomeResult(
        harness_decision_id=decision_id,
        harness_run_id=run_id,
        ticker_code=ticker_code,
        horizon_days=horizon_days,
        status=status,
        actual_holding_days=actual_holding_days,
        raw_return=raw_return,
        benchmark_return=benchmark_return,
        alpha_return=alpha_return,
        error=error,
    )


def _horizon_may_still_elapse(entry_date: date, evaluated_at: date, horizon_days: int) -> bool:
    """True while fewer calendar days than a generous horizon window have passed."""

    calendar_window = int(horizon_days * 1.6) + 7
    return (evaluated_at - entry_date).days <= calendar_window


def _benchmark_symbol(ticker_code: str) -> str | None:
    try:
        return resolve_kr_ticker(ticker_code, lookup_pykrx=False).benchmark_symbol
    except Exception:
        return None


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()
