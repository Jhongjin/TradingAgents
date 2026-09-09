from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.site.home_page import THEMES, build_home_view_model, render_home_page
from tradingagents.storage import HarnessDecisionInput, HarnessOutcomeInput, HarnessRunInput, StorageRepository, create_storage_engine

NOW = datetime(2026, 9, 9, 10, 19, tzinfo=ZoneInfo("Asia/Seoul"))


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _seed(repo: StorageRepository, as_of: date = date(2026, 9, 8)) -> str:
    run_id = repo.create_harness_run(
        HarnessRunInput(as_of_date=as_of, broker="kis", dry_run=False, confirmer="debate", universe_size=198, candidate_count=4, order_count=1, cash_before=50_000_000, cash_after=44_443_220)
    )
    debate = {
        "turns": {
            "bull": {"status": "ok", "data": {"thesis": "20일 모멘텀이 살아났고 거래량이 따라붙었다."}},
            "bear": {"status": "ok", "data": {"thesis": "60일 추세는 아직 음수다. <script>alert(1)</script>"}},
            "judge": {"status": "ok", "data": {"rationale": "방향은 위다. 분할로, 작은 비중으로."}},
            "risk_panel": {"status": "ok", "data": {"risk_score": 0.78, "stop_loss_pct": 0.08, "take_profit_pct": 0.12, "neutral_view": "허용."}},
        }
    }
    decision_id = repo.add_harness_decision(
        HarnessDecisionInput(
            harness_run_id=run_id, as_of_date=as_of, ticker_code="000660", stage="ordered", ticker_name="SK하이닉스", market="KOSPI",
            screener_rank=1, composite_score=0.71, forecast_expected_return=0.034, forecast_probability_up=0.61,
            confirmation_rating="Overweight", confirmation_confidence=0.78, confirmation_source="debate", quantity=3, order_status="accepted",
            reasons=["모의투자 매수주문이 완료되었습니다."],
            detail={"confirmation": {"rationale": "분할 진입이 적절합니다.", "position_weight": 0.11, "raw": {"debate": debate}}},
        )
    )
    repo.add_harness_decision(
        HarnessDecisionInput(harness_run_id=run_id, as_of_date=as_of, ticker_code="005930", stage="forecast_rejected", ticker_name="삼성전자", market="KOSPI", screener_rank=2, forecast_expected_return=0.011, forecast_probability_up=0.55, reasons=["probability up 55% below 55%"])
    )
    repo.upsert_harness_outcome(HarnessOutcomeInput(harness_decision_id=decision_id, harness_run_id=run_id, ticker_code="000660", entry_date=as_of, evaluated_at=as_of, horizon_days=5, status="pending"))
    return run_id


def test_home_view_model_without_storage_has_waiting_headline():
    model = build_home_view_model(None, now=NOW)
    assert model["run"] is None
    assert "기다리고" in model["headline"]
    assert model["decisions"] == []
    assert model["debate"] == []
    assert len(model["rail"]) == 6


def test_home_view_model_from_seeded_run_builds_headline_debate_and_funnel():
    repo = _repo()
    _seed(repo)
    model = build_home_view_model(repo, site_base_url="https://example.com", now=NOW)
    assert model["headline"] == "2개 후보 중 1개가 떨어졌다. SK하이닉스만 남은 이유"
    assert model["deck"].startswith("분할 진입")
    assert [item["label"] for item in model["debate"]] == ["강세 의견", "약세 의견", "판정", "리스크 점검"]
    assert "손절 -8%" in model["debate"][3]["text"] and "익절 +12%" in model["debate"][3]["text"]
    assert [(step["label"], step["value"]) for step in model["funnel"]] == [("대상 종목", 198), ("후보", 4), ("AI 토론 통과", 1), ("모의 주문", 1)]
    assert model["account"]["cash_after"] == 44_443_220
    assert model["issue_number"] == 1
    assert model["canonical"] == "https://example.com/"


def test_render_home_page_escapes_debate_text_and_offers_themes():
    repo = _repo()
    _seed(repo)
    html = render_home_page(repo=repo, now=NOW)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "SK하이닉스만 남은 이유" in html
    assert "SK하이닉스, 이렇게 결정됐습니다" in html
    for theme in THEMES:
        assert f'data-theme="{theme}"' in html
    assert ':root[data-theme="dark"]' in html and ':root[data-theme="paper"]' in html
    assert "prefers-color-scheme: dark" in html
    assert "localStorage.getItem('ta-theme')" in html
    assert 'data-rail-tickers="005930,000660,035420,373220,086520,196170"' in html
    assert "실계좌 주문은 이 사이트에서 일어나지 않습니다" in html
    assert "가상 매수" not in html.split("</table>")[1]  # no order-execution wording outside the ledger
    assert "주문 실행" not in html


def test_render_home_page_without_repo_shows_empty_states():
    html = render_home_page(repo=None, now=NOW)
    assert "첫 종목 선별을 기다리고 있습니다" in html
    assert "아직 저장된 선별 결과가 없습니다" in html
    assert "20일 성과가 확정되면" in html


def test_api_app_serves_new_home_and_legacy_home():
    repo = _repo()
    _seed(repo)
    client = TestClient(create_app(repo=repo, load_repo_from_env=False, public_cache_seconds=60))
    response = client.get("/")
    assert response.status_code == 200
    assert "SK하이닉스만 남은 이유" in response.text
    assert response.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=120"
    legacy = client.get("/?legacy=1")
    assert legacy.status_code == 200
    assert "한국 주식 AI 관제 시스템" in legacy.text


def test_home_sources_are_memoised_per_repo(monkeypatch):
    from tradingagents.site import home_page

    repo = _repo()
    _seed(repo)
    home_page.clear_home_cache()
    calls = []
    original = home_page.build_harness_run_payload
    monkeypatch.setattr(home_page, "build_harness_run_payload", lambda r, **kw: (calls.append(1), original(r, **kw))[1])
    build_home_view_model(repo, now=NOW)
    build_home_view_model(repo, now=NOW)
    assert len(calls) == 1
    home_page.clear_home_cache()
    build_home_view_model(repo, now=NOW)
    assert len(calls) == 2


def test_home_shows_free_view_with_today_teaser():
    repo = _repo()
    _seed(repo, date(2026, 9, 8))
    repo.create_harness_run(HarnessRunInput(as_of_date=date(2026, 9, 9), confirmer="debate", candidate_count=20, order_count=2))
    model = build_home_view_model(repo, now=NOW)
    assert model["run"]["as_of_date"] == "2026-09-08"  # free view: previous day
    assert model["teaser"] == {"as_of_date": "2026-09-09", "candidate_count": 20, "order_count": 2, "confirmer": "debate"}
    assert [item["role"] for item in model["debate"]] == ["bull", "bear", "judge", "risk_panel"]  # excerpts only
    html = render_home_page(repo=repo, now=NOW)
    assert "오늘" in html and "데일리 패스" in html and "후보 20개 중 2개 통과" in html


def test_home_forwards_auth_hash_to_member_page():
    html = render_home_page(repo=None, now=NOW)
    assert "location.replace('/member'+h)" in html
    assert "access_token=" in html
