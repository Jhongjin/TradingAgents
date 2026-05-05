from datetime import date

import pytest

from tradingagents.site import queue_analysis_refresh_request
from tradingagents.storage import StorageRepository, create_storage_engine


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


def test_queue_analysis_refresh_request_rejects_non_korean_ticker():
    repo = _repo()

    with pytest.raises(ValueError, match="Korean 6-digit"):
        queue_analysis_refresh_request(repo, ticker="AAPL", user_id=USER_ID)
