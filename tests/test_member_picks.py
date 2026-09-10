"""Member preferences: filtering the daily picks down to what one member wants."""

from datetime import date

from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.site.member_preferences import filter_picks, normalize
from tradingagents.storage import HarnessDecisionInput, HarnessRunInput, StorageRepository, create_storage_engine

USER = "11111111-1111-4111-8111-111111111111"

PICKS = [
    {"ticker_code": "005930", "ticker_name": "삼성전자", "market": "KOSPI", "confirmation_rating": "Buy", "entry_price": 70000, "stage": "ordered"},
    {"ticker_code": "131290", "ticker_name": "티에스이", "market": "KOSDAQ", "confirmation_rating": "Overweight", "entry_price": 308000, "stage": "ordered"},
    {"ticker_code": "069500", "ticker_name": "KODEX 200", "market": "KOSPI", "confirmation_rating": "Buy", "entry_price": 45000, "stage": "ordered"},
    {"ticker_code": "000660", "ticker_name": "SK하이닉스", "market": "KOSPI", "confirmation_rating": "Neutral", "entry_price": 1852000, "stage": "ordered"},
]


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def test_defaults_keep_everything_except_etfs():
    result = filter_picks(PICKS, None)
    assert [item["ticker_code"] for item in result["items"]] == ["005930", "131290", "000660"]
    assert result["dropped"] == [{"reason": "etf", "label": "ETF 제외", "count": 1}]
    assert result["total_count"] == 4 and result["kept_count"] == 3


def test_each_condition_removes_what_it_says():
    kospi_only = filter_picks(PICKS, {"markets": ["KOSPI"]})
    assert "131290" not in {item["ticker_code"] for item in kospi_only["items"]}

    affordable = filter_picks(PICKS, {"max_price": 100000})
    assert {item["ticker_code"] for item in affordable["items"]} == {"005930"}
    assert any(entry["reason"] == "price" for entry in affordable["dropped"])

    strong = filter_picks(PICKS, {"min_rating": "buy"})
    assert {item["ticker_code"] for item in strong["items"]} == {"005930"}  # Overweight and Neutral fall below

    excluded = filter_picks(PICKS, {"excluded_tickers": ["005930"]})
    assert "005930" not in {item["ticker_code"] for item in excluded["items"]}


def test_bad_input_falls_back_instead_of_filtering_everything_away():
    prefs = normalize({"markets": ["NASDAQ"], "min_rating": "nonsense", "max_price": -5, "excluded_tickers": ["nope", "005930"]})
    assert prefs["markets"] == ["KOSPI", "KOSDAQ"]
    assert prefs["min_rating"] == "any" and prefs["max_price"] is None
    assert prefs["excluded_tickers"] == ["005930"]
    assert filter_picks(PICKS, prefs)["kept_count"] == 2  # only the ETF and the excluded name go


def test_preferences_round_trip_and_narrow_the_member_picks(monkeypatch):
    repo = _repo()
    yesterday = date(2026, 9, 9)
    run = repo.create_harness_run(
        HarnessRunInput(as_of_date=yesterday, confirmer="debate", visibility="public", dry_run=False, broker="paper", candidate_count=4, order_count=4)
    )
    for pick in PICKS:
        repo.add_harness_decision(
            HarnessDecisionInput(
                harness_run_id=run,
                as_of_date=yesterday,
                ticker_code=pick["ticker_code"],
                ticker_name=pick["ticker_name"],
                market=pick["market"],
                stage="ordered",
                confirmation_rating=pick["confirmation_rating"],
                order_status="filled",
                reasons=["paper fill"],
            )
        )
    monkeypatch.setenv("TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER", "true")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))
    headers = {"X-TradingAgents-User-Id": USER}

    first = client.get("/api/member/preferences", headers=headers).json()
    assert first["saved"] is False and first["preferences"]["markets"] == ["KOSPI", "KOSDAQ"]

    saved = client.put(
        "/api/member/preferences",
        json={"markets": ["KOSPI"], "exclude_etf": True, "min_rating": "buy", "max_price": 100000, "excluded_tickers": []},
        headers=headers,
    ).json()
    assert saved["status"] == "saved" and saved["preferences"]["min_rating"] == "buy"
    assert client.get("/api/member/preferences", headers=headers).json()["saved"] is True

    picks = client.get("/api/member/picks", headers=headers).json()
    assert [item["ticker_code"] for item in picks["items"]] == ["005930"]
    assert picks["total_count"] == 4 and picks["kept_count"] == 1
    assert picks["as_of_date"] == "2026-09-09"
    # each row is dropped by the first condition it fails; which one depends on
    # how the stored market resolved, so only the count is asserted here
    assert picks["dropped_count"] == 3
    assert {entry["reason"] for entry in picks["dropped"]} <= {"market", "etf", "rating", "price", "excluded"}


def test_the_member_page_carries_the_condition_card():
    from tradingagents.site.web_pages import render_member_dashboard_page

    html = render_member_dashboard_page()
    for needle in ("memberPicksCard", "조건 바꾸기", "/api/member/picks", "/api/member/preferences", "loadMemberPicks", "최소 등급"):
        assert needle in html, needle


def test_a_member_can_exclude_a_whole_sector(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.site.member_preferences._sector_of",
        lambda code: {"005930": "반도체", "131290": "반도체", "000660": "반도체"}.get(code, "정유"),
    )
    result = filter_picks(PICKS, {"excluded_sectors": ["반도체"], "exclude_etf": False})
    assert {item["ticker_code"] for item in result["items"]} == {"069500"}
    assert [entry["label"] for entry in result["dropped"]] == ["제외 업종"]
    assert result["items"][0]["sector"] == "정유"


def test_sector_preferences_survive_a_save_and_load(monkeypatch):
    repo = _repo()
    monkeypatch.setenv("TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER", "true")
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=True))
    headers = {"X-TradingAgents-User-Id": USER}

    client.put("/api/member/preferences", json={"excluded_sectors": ["정유", "정유", "  은행 "]}, headers=headers)
    stored = client.get("/api/member/preferences", headers=headers).json()["preferences"]
    assert stored["excluded_sectors"] == ["정유", "은행"]
