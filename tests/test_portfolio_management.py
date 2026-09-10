from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.storage import ManualTradeInput, StorageRepository, create_storage_engine

USER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _client(repo, monkeypatch) -> TestClient:
    monkeypatch.setenv("TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER", "true")
    return TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))


def test_repository_rename_delete_portfolio_trade_and_target():
    repo = _repo()
    pid = repo.create_manual_portfolio(user_id=USER, name="테스트")
    tid = repo.add_manual_trade(ManualTradeInput(portfolio_id=pid, ticker_code="005930", side="buy", trade_date=date(2026, 9, 7), price=Decimal("89000"), quantity=Decimal("20")))
    repo.set_price_target(portfolio_id=pid, ticker_code="005930", target_price=Decimal("120000"), stop_price=Decimal("85000"))

    assert repo.update_manual_portfolio(portfolio_id=pid, name="장기")["name"] == "장기"
    assert repo.delete_price_target(portfolio_id=pid, ticker_code="005930") is True
    assert repo.delete_price_target(portfolio_id=pid, ticker_code="005930") is False
    assert repo.delete_manual_trade(portfolio_id=pid, trade_id=tid) is True
    assert repo.manual_trades_for_portfolio(pid) == []
    repo.delete_manual_portfolio(pid)
    assert repo.get_manual_portfolio(pid) is None


def test_portfolio_management_routes_enforce_ownership(monkeypatch):
    repo = _repo()
    client = _client(repo, monkeypatch)
    headers = {"X-TradingAgents-User-Id": USER}
    pid = client.post("/api/portfolios", json={"name": "내 일지"}, headers=headers).json()["portfolio_id"]
    tid = repo.add_manual_trade(ManualTradeInput(portfolio_id=pid, ticker_code="005930", side="buy", trade_date=date(2026, 9, 7), price=Decimal("89000"), quantity=Decimal("20")))
    repo.set_price_target(portfolio_id=pid, ticker_code="005930", target_price=Decimal("120000"))

    renamed = client.patch(f"/api/portfolios/{pid}", json={"name": "새 이름"}, headers=headers)
    assert renamed.status_code == 200 and renamed.json()["portfolio"]["name"] == "새 이름"
    assert client.patch(f"/api/portfolios/{pid}", json={"name": "훔치기"}, headers={"X-TradingAgents-User-Id": OTHER}).status_code in (403, 404)

    assert client.delete(f"/api/portfolios/{pid}/targets/005930", headers=headers).json()["status"] == "deleted"
    assert client.delete(f"/api/portfolios/{pid}/targets/005930", headers=headers).status_code == 404
    assert client.delete(f"/api/portfolios/{pid}/trades/{tid}", headers=headers).json()["status"] == "deleted"
    assert client.delete(f"/api/portfolios/{pid}/trades/{tid}", headers=headers).status_code == 404
    assert client.delete(f"/api/portfolios/{pid}", headers={"X-TradingAgents-User-Id": OTHER}).status_code in (403, 404)
    assert client.delete(f"/api/portfolios/{pid}", headers=headers).json()["status"] == "deleted"
    assert repo.get_manual_portfolio(pid) is None


def test_member_page_js_manages_journals_and_colors_pnl():
    from tradingagents.site.web_pages import render_member_dashboard_page

    html = render_member_dashboard_page()
    for needle in ("portfolioManageRow", "tradeActionList", "positionActionList", "decorateSigned", 'method: "PATCH", body: JSON.stringify({ name })', "/trades/${encodeURIComponent(trade.id)}", "include_latest_prices=false", "include_latest_prices=true"):
        assert needle in html, needle
