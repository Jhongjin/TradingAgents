from decimal import Decimal

import pytest

from tradingagents.site import build_watchlist_payload
from tradingagents.storage import StorageRepository, create_storage_engine


USER_ID = "00000000-0000-0000-0000-000000000001"


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def test_watchlist_payload_includes_items_and_current_prices():
    repo = _repo()
    watchlist_id = repo.create_watchlist(user_id=USER_ID, name="관심종목")
    repo.add_watchlist_item(watchlist_id=watchlist_id, ticker_code="005930", memo="memory leader")
    repo.add_watchlist_item(watchlist_id=watchlist_id, ticker_code="000660")

    payload = build_watchlist_payload(
        repo,
        watchlist_id,
        current_prices={"005930": Decimal("83000")},
    )

    assert payload["watchlist"]["name"] == "관심종목"
    assert payload["item_count"] == 2
    assert payload["priced_item_count"] == 1
    assert payload["pricing_status"] == "partial"
    assert payload["summary"] == {"memo_item_count": 1, "unpriced_item_count": 1}
    items = {item["ticker_code"]: item for item in payload["items"]}
    assert items["005930"]["ticker_name"] == "삼성전자"
    assert items["005930"]["current_price"] == 83000.0
    assert items["005930"]["has_memo"] is True
    assert items["005930"]["public_stock_path"] == "/stocks/005930"
    assert items["000660"]["current_price"] is None
    assert items["000660"]["has_memo"] is False


def test_watchlist_payload_rejects_missing_watchlist():
    repo = _repo()

    with pytest.raises(ValueError, match="watchlist not found"):
        build_watchlist_payload(repo, USER_ID)
