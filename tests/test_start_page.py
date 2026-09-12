"""The arrival path: a one-screen explanation, and a strip that offers it once."""

import pytest
from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.storage import StorageRepository, create_storage_engine


@pytest.fixture(autouse=True)
def _plans_off(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_PAID_PLANS_ENABLED", raising=False)


def _client() -> TestClient:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return TestClient(create_app(repo=repo, load_repo_from_env=False, trust_member_user_header=False))


def test_the_page_answers_what_this_is_what_is_open_and_what_signing_up_adds():
    page = _client().get("/start").text

    assert "AI가 매일 아침 종목을 고르고, 맞았는지까지 공개합니다" in page
    for stage in ("규칙이 먼저 거릅니다", "AI가 토론해 확인합니다", "모의 계좌가 실제로 담습니다", "맞았는지 공개합니다"):
        assert stage in page
    assert "지금 열려 있는 것" in page and "가입하지 않아도" in page
    assert "가입하면 여기에 더해집니다" in page
    for perk in ("아침 알림", "목표가 도달 알림", "매매 일지", "공시 알림", "주간 리포트"):
        assert perk in page

    # it sells nothing, and says so
    assert "결제는 없습니다" in page and "전부 무료입니다" in page
    assert "월 10,000원" not in page and "데일리 패스" not in page
    # and it never reads as advice
    assert "매매 권유가 아닙니다" in page and "실계좌 주문" in page

    assert 'href="/harness"' in page and 'href="/member?mode=signup"' in page
    assert '<link rel="canonical" href="' in page and "/start" in page
    assert "noindex" not in page                                    # a first-visit page belongs in search


def test_the_strip_is_offered_on_public_pages_and_not_where_it_would_be_noise():
    client = _client()

    home = client.get("/").text
    assert '<div class="intro-strip" id="intro-strip" hidden>' in home
    assert "처음 오셨나요?" in home and 'href="/start" data-intro-go' in home
    assert "ta-intro-seen" in home                                   # the browser decides whether to reveal it

    assert 'id="intro-strip"' not in client.get("/start").text       # not on the page it points to
    assert 'id="intro-strip"' not in client.get("/mypage").text      # nor on a member's own pages
    assert 'id="intro-strip"' not in client.get("/billing").text

    for path in ("/harness", "/paper", "/outcomes", "/pricing"):
        assert 'id="intro-strip"' in client.get(path).text, path


def test_the_strip_covers_nothing_and_leaves_once_answered():
    home = _client().get("/").text
    body_start = home.index("<body")
    strip_at = home.index('id="intro-strip"', body_start)
    main_at = home.index('id="main-content"', body_start)
    assert strip_at < main_at                                        # above the content, never over it
    assert "position: fixed" not in home.split(".ds .intro-strip")[1].split("}")[0]

    # both answers are remembered, so the strip is a one-time question
    script = home[home.rindex("first-visit strip"):]
    assert "data-intro-close" in script and "data-intro-go" in script
    assert script.count("remember") >= 3
    assert "if(seen || token) return;" in script                     # a member is not a first-time visitor


def test_the_map_the_site_publishes_leads_with_it():
    client = _client()
    sitemap = client.get("/sitemap.xml").text
    assert "/start</loc>" in sitemap
    llms = client.get("/llms.txt").text
    assert "30초 안내" in llms and "/start" in llms
    assert '<a href="/start">30초 안내</a>' in client.get("/").text   # and the footer links it first
