"""Background worker helpers for queued analysis refresh requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Any

from tradingagents.storage import StorageRepository


AnalysisRunner = Callable[[Mapping[str, Any]], str]

_SECRET_PATTERN = re.compile(r"\b(sk|rk|pk|xoxb|ghp|gho|glpat|AIza)[-_A-Za-z0-9]{6,}")
MAX_FAILURE_REASON_CHARS = 300


def scrub_failure_reason(text: str, *, limit: int = MAX_FAILURE_REASON_CHARS) -> str:
    """Drop credential-shaped tokens and cap the length before persisting an error.

    Provider errors echo the key they rejected, so the raw text must never reach
    the member-facing request row.
    """

    cleaned = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}-***", str(text or "").strip())
    cleaned = re.sub(r"\*{4,}", "***", cleaned)
    return cleaned if len(cleaned) <= limit else f"{cleaned[: limit - 3]}..."


@dataclass(frozen=True)
class AnalysisWorkerResult:
    request_id: str
    ticker_code: str
    status: str
    analysis_run_id: str | None = None
    error: str | None = None


STALE_RUNNING_MINUTES = 45


def requeue_stale_running_requests(
    repo: StorageRepository,
    *,
    older_than_minutes: int = STALE_RUNNING_MINUTES,
    now: datetime | None = None,
    limit: int = 20,
) -> list[str]:
    """Return long-running requests to the queue.

    A worker that is killed mid-run (a function timeout, a cancelled job) leaves
    the row marked running forever, so the member sees no progress and no
    failure. Anything older than the cutoff goes back to queued for the next
    pass.
    """

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=older_than_minutes)
    requeued: list[str] = []
    for request in repo.list_analysis_requests(status="running", limit=limit):
        updated_at = request.get("updated_at") or request.get("created_at")
        if isinstance(updated_at, datetime):
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if updated_at > cutoff:
                continue
        else:
            continue
        repo.update_analysis_request_status(str(request["id"]), status="queued")
        requeued.append(str(request["id"]))
    return requeued


def process_queued_analysis_requests(
    repo: StorageRepository,
    runner: AnalysisRunner,
    *,
    limit: int = 1,
) -> list[AnalysisWorkerResult]:
    """Process queued analysis requests with an injected runner.

    The runner receives one queued request row and must return the persisted
    `analysis_runs.id`. This keeps worker orchestration independent from the
    expensive TradingAgents graph and easy to test.
    """

    if limit <= 0:
        raise ValueError("limit must be positive")

    results: list[AnalysisWorkerResult] = []
    for request in repo.list_analysis_requests(status="queued", limit=limit):
        request_id = request["id"]
        ticker_code = request["ticker_code"]
        repo.update_analysis_request_status(request_id, status="running")
        try:
            analysis_run_id = runner(request)
        except Exception as exc:
            error = scrub_failure_reason(f"{exc.__class__.__name__}: {exc}")
            repo.update_analysis_request_status(request_id, status="failed", reason=error)
            results.append(
                AnalysisWorkerResult(
                    request_id=request_id,
                    ticker_code=ticker_code,
                    status="failed",
                    error=error,
                )
            )
            continue

        repo.update_analysis_request_status(
            request_id,
            status="completed",
            analysis_run_id=analysis_run_id,
        )
        results.append(
            AnalysisWorkerResult(
                request_id=request_id,
                ticker_code=ticker_code,
                status="completed",
                analysis_run_id=analysis_run_id,
            )
        )
    return results
