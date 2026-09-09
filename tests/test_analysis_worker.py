from datetime import date

import pytest

from tradingagents.site.analysis_worker import process_queued_analysis_requests
from tradingagents.storage.repository import TEST_DATABASE_URL  # noqa: E402
from tradingagents.storage import AnalysisRequestInput, AnalysisRunInput, StorageRepository, create_storage_engine


USER_ID = "00000000-0000-0000-0000-000000000001"


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine(TEST_DATABASE_URL))
    repo.create_schema()
    return repo


def _queue_request(repo: StorageRepository) -> str:
    return repo.create_analysis_request(
        AnalysisRequestInput(
            user_id=USER_ID,
            ticker_code="005930",
            requested_trade_date=date(2026, 5, 5),
            reason="실적 발표 전 재점검",
        )
    )


def test_analysis_worker_marks_request_completed_with_analysis_run():
    repo = _repo()
    request_id = _queue_request(repo)

    def runner(request):
        assert request["id"] == request_id
        run_id = repo.create_analysis_run(
            AnalysisRunInput(
                ticker_code=request["ticker_code"],
                trade_date=request["requested_trade_date"],
                status="completed",
            )
        )
        repo.complete_analysis_run(run_id)
        return run_id

    results = process_queued_analysis_requests(repo, runner)
    completed = repo.list_analysis_requests(status="completed")

    assert len(results) == 1
    assert results[0].status == "completed"
    assert completed[0]["analysis_run_id"] == results[0].analysis_run_id


def test_analysis_worker_marks_request_failed_when_runner_raises():
    repo = _repo()
    _queue_request(repo)

    def runner(_request):
        raise RuntimeError("LLM unavailable")

    results = process_queued_analysis_requests(repo, runner)
    failed = repo.list_analysis_requests(status="failed")

    assert results[0].status == "failed"
    assert "LLM unavailable" in results[0].error
    assert failed[0]["status"] == "failed"
    assert failed[0]["reason"] == "실적 발표 전 재점검"
    assert failed[0]["metadata_json"]["request_reason"] == "실적 발표 전 재점검"
    assert "LLM unavailable" in failed[0]["metadata_json"]["failure_reason"]


def test_analysis_worker_rejects_invalid_limit():
    repo = _repo()

    with pytest.raises(ValueError, match="limit must be positive"):
        process_queued_analysis_requests(repo, lambda _request: "unused", limit=0)
