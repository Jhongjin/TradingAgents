import pytest
from fastapi.testclient import TestClient

from tradingagents.screener import MarketSnapshot, MarketSnapshotRow, ScreenerConfig, screen_korean_market
from tradingagents.site.api_app import create_app
from tradingagents.site.screener_api import build_forecast_payload, build_screener_payload


def _points(count=200, drift=0.004):
    rows = []
    close = 50_000.0
    for index in range(count):
        close *= 1 + drift
        rows.append({"date": f"2026-01-{index % 28 + 1:02d}", "close": round(close, 2), "volume": 1_000_000})
    return rows


def _fake_screen(as_of_date, *, config, **kwargs):
    snapshot = MarketSnapshot(
        as_of_date="2026-09-05",
        markets=config.markets,
        rows=[MarketSnapshotRow("005930", "삼성전자", "KOSPI", 70_000.0, 1e7, 5e11, 4e14, 0.5, 12.0, 1.2, 2.0)],
    )
    return screen_korean_market(snapshot=snapshot, history_fetcher=lambda code, s, e: _points(), config=config)


def test_build_screener_payload_uses_runner_and_notices():
    payload = build_screener_payload(markets="kospi", top_n=5, max_per=30, screener_runner=_fake_screen)
    assert payload["status"] == "available"
    assert payload["markets"] == ["KOSPI"]
    assert payload["config"]["max_per"] == 30.0
    assert payload["candidates"][0]["code"] == "005930"
    assert payload["execution_boundary"] == "screening_only_no_orders"
    assert payload["notices"]
    with pytest.raises(ValueError):
        build_screener_payload(top_n=0)
    with pytest.raises(ValueError):
        build_screener_payload(top_n=500)


def test_build_forecast_payload_from_history():
    payload = build_forecast_payload("005930", as_of_date="2026-09-05", horizon_days=10, history_fetcher=lambda c, s, e: _points())
    assert payload["status"] == "available"
    assert payload["forecast"]["horizon"] == 10
    assert payload["forecast"]["backend"] == "naive"
    assert payload["factors"]["composite"] > 0
    assert payload["risk_metrics"]["observations"] == 200
    assert payload["execution_boundary"] == "forecast_only_no_orders"

    thin = build_forecast_payload("005930", as_of_date="2026-09-05", history_fetcher=lambda c, s, e: _points(1))
    assert thin["status"] == "insufficient_price_data"
    with pytest.raises(ValueError):
        build_forecast_payload("AAPL")
    with pytest.raises(ValueError):
        build_forecast_payload("005930", horizon_days=0)


def test_api_app_serves_screener_and_forecast(monkeypatch):
    monkeypatch.setattr("tradingagents.site.screener_api.screen_korean_market", _fake_screen)
    monkeypatch.setattr("tradingagents.site.screener_api._default_history_fetcher", lambda vendor: (lambda c, s, e: _points()))
    client = TestClient(create_app(repo=None, load_repo_from_env=False))

    response = client.get("/api/screener", params={"markets": "KOSPI", "top_n": 3})
    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("public")
    assert response.json()["candidates"][0]["name"] == "삼성전자"

    response = client.get("/api/forecast/005930", params={"horizon_days": 5, "as_of_date": "2026-09-05"})
    assert response.status_code == 200
    assert response.json()["forecast"]["horizon"] == 5
    assert response.headers["cache-control"].startswith("public")

    response = client.get("/api/forecast/AAPL")
    assert response.status_code == 400
    response = client.get("/api/screener", params={"markets": "NASDAQ"})
    assert response.status_code == 422
