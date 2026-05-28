import pytest
from fastapi.testclient import TestClient

from tradingagents.site import build_ticker_search_payload
from tradingagents.site.api_app import create_app


def test_ticker_search_payload_returns_korean_ticker_matches():
    payload = build_ticker_search_payload("삼성", lookup_pykrx=False)

    assert payload["status"] == "available"
    assert payload["query"] == "삼성"
    assert payload["items"][0]["code"] == "005930"
    assert payload["items"][0]["name"] == "삼성전자"
    assert payload["items"][0]["currency"] == "KRW"
    assert payload["items"][0]["yfinance_symbol"] == "005930.KS"


def test_ticker_search_payload_accepts_rokit_healthcare_common_typo():
    payload = build_ticker_search_payload("로켓헬스케어", lookup_pykrx=False)

    assert payload["items"][0]["code"] == "376900"
    assert payload["items"][0]["name"] == "로킷헬스케어"
    assert payload["items"][0]["market"] == "KOSDAQ"
    assert payload["items"][0]["yfinance_symbol"] == "376900.KQ"


def test_ticker_search_payload_validates_limit():
    with pytest.raises(ValueError, match="cannot exceed 50"):
        build_ticker_search_payload("삼성", limit=51, lookup_pykrx=False)


def test_api_app_serves_ticker_search():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/api/tickers/search", params={"q": "삼성", "lookup_pykrx": "false"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300, stale-while-revalidate=600"
    assert response.json()["items"][0]["code"] == "005930"


def test_api_app_rejects_invalid_ticker_search_limit():
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/api/tickers/search", params={"q": "삼성", "limit": 51})

    assert response.status_code == 400
    assert "cannot exceed 50" in response.json()["detail"]
