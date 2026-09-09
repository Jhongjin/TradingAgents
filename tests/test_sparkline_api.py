from dataclasses import dataclass

from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.site import market_api


@dataclass
class _Point:
    date: str
    close: float | None


@dataclass
class _Series:
    ticker_code: str
    ticker_name: str
    vendor: str
    points: list


def _loader(code: str):
    if code == "999999":
        raise RuntimeError("vendor down")
    pts = [_Point(f"2026-08-{i + 1:02d}", 100.0 + i) for i in range(70)]
    pts.append(_Point("2026-09-09", None))
    return _Series(ticker_code=code, ticker_name=f"N{code}", vendor="pykrx", points=pts)


def test_sparkline_payload_trims_caches_and_isolates_errors():
    market_api._sparkline_cache.clear()
    calls = []

    def loader(code):
        calls.append(code)
        return _loader(code)

    payload = market_api.build_sparkline_payload(["005930", "999999"], days=60, series_loader=loader)
    assert payload["status"] == "partial" and payload["days"] == 60
    assert len(payload["series"]["005930"]["closes"]) == 60 and payload["series"]["005930"]["closes"][-1] == 169.0
    assert "999999" in payload["errors"]

    again = market_api.build_sparkline_payload(["005930"], days=60, series_loader=loader)
    assert again["status"] == "available" and calls.count("005930") == 1  # memoised


def test_sparkline_endpoint_validates_and_serves(monkeypatch):
    market_api._sparkline_cache.clear()
    monkeypatch.setattr(market_api, "get_ohlcv_chart_series", lambda code, start, end, vendor="pykrx": _loader(code))
    client = TestClient(create_app(repo=None, load_repo_from_env=False))
    response = client.get("/api/prices/sparkline?tickers=005930,000660&days=30")
    assert response.status_code == 200
    body = response.json()
    assert set(body["series"]) == {"005930", "000660"} and len(body["series"]["000660"]["closes"]) == 30
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    assert client.get("/api/prices/sparkline?tickers=").status_code == 400
