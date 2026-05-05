from datetime import date

import pytest

from tradingagents.site import build_public_analysis_feed_payload, queue_analysis_refresh_request
from tradingagents.storage import AnalysisRunInput, StorageRepository, create_storage_engine


USER_ID = "00000000-0000-0000-0000-000000000001"


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def test_queue_analysis_refresh_request_persists_queued_request():
    repo = _repo()

    payload = queue_analysis_refresh_request(
        repo,
        ticker="005930",
        user_id=USER_ID,
        requested_trade_date="2026-05-05",
        reason="stale",
    )
    queued = repo.list_analysis_requests(user_id=USER_ID)

    assert payload["status"] == "queued"
    assert payload["ticker"]["code"] == "005930"
    assert payload["requested_trade_date"] == "2026-05-05"
    assert queued[0]["id"] == payload["request_id"]
    assert queued[0]["requested_trade_date"] == date(2026, 5, 5)


def test_queue_analysis_refresh_request_reuses_existing_active_request():
    repo = _repo()

    first = queue_analysis_refresh_request(
        repo,
        ticker="005930",
        user_id=USER_ID,
        requested_trade_date="2026-05-05",
        reason="stale",
    )
    second = queue_analysis_refresh_request(
        repo,
        ticker="005930",
        user_id=USER_ID,
        requested_trade_date="2026-05-05",
        reason="button retry",
    )
    queued = repo.list_analysis_requests(user_id=USER_ID)

    assert first["status"] == "queued"
    assert second["status"] == "already_queued"
    assert second["request_id"] == first["request_id"]
    assert len(queued) == 1


def test_queue_analysis_refresh_request_rejects_non_korean_ticker():
    repo = _repo()

    with pytest.raises(ValueError, match="Korean 6-digit"):
        queue_analysis_refresh_request(repo, ticker="AAPL", user_id=USER_ID)


def test_public_analysis_feed_lists_completed_public_runs_only():
    repo = _repo()
    public_run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
        )
    )
    private_run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 6),
            visibility="private",
        )
    )
    pending_run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name="삼성전자",
            market="KOSPI",
            trade_date=date(2026, 5, 7),
            visibility="public",
        )
    )
    repo.complete_analysis_run(public_run_id)
    repo.complete_analysis_run(private_run_id)

    payload = build_public_analysis_feed_payload(repo, ticker="005930.KS")

    assert payload["ticker_code"] == "005930"
    assert [item["id"] for item in payload["items"]] == [public_run_id]
    assert private_run_id not in [item["id"] for item in payload["items"]]
    assert pending_run_id not in [item["id"] for item in payload["items"]]


def test_public_analysis_feed_validates_limit():
    repo = _repo()

    with pytest.raises(ValueError, match="cannot exceed 1"):
        build_public_analysis_feed_payload(repo, limit=2, max_limit=1)
