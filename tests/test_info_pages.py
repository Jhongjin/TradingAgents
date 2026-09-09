import pytest

from tradingagents.site.info_pages import (
    render_feature_detail_page,
    render_feature_index_page,
    render_policy_page,
)
from tradingagents.site.web_pages import FEATURE_DETAIL_PAGES, POLICY_PAGES


def test_feature_index_page_uses_shell_and_links_every_feature():
    html = render_feature_index_page(site_base_url="https://example.com")

    assert '<body class="ds ' in html
    assert "<title>처음 시작하기 | TradingAgents Korea</title>" in html
    assert '<link rel="canonical" href="https://example.com/features">' in html
    assert '<meta property="og:url" content="https://example.com/features">' in html
    assert "종목을 읽고, 필요한 기록만 마이페이지에 남깁니다" in html
    assert "주문은 실행하지 않습니다." in html
    for page in FEATURE_DETAIL_PAGES.values():
        assert f'href="{page["path"]}"' in html
    assert 'href="/stocks/005930">샘플 종목 보기</a>' in html
    assert 'href="/member?mode=signup">마이페이지 만들기</a>' in html
    assert 'href="/analyses">공개 분석 보기</a>' in html
    assert "권장 운영 순서" not in html
    # jargon replaced in visible copy
    assert "내 공간" not in html
    assert "사후 결과" not in html
    assert "/api/member/dashboard" not in html
    assert "/api/portfolios" not in html
    assert 'name="robots"' not in html


@pytest.mark.parametrize("slug", list(FEATURE_DETAIL_PAGES))
def test_feature_detail_pages_keep_canonical_path_and_description(slug):
    page = FEATURE_DETAIL_PAGES[slug]
    html = render_feature_detail_page(slug, site_base_url="https://example.com")

    assert '<body class="ds ' in html
    assert f'<link rel="canonical" href="https://example.com{page["path"]}">' in html
    assert f'<meta name="description" content="{page["description"]}">' in html
    assert f'<meta property="og:url" content="https://example.com{page["path"]}">' in html
    assert f'href="{page["cta_href"]}"' in html
    assert "데이터 경계" in html
    assert "필요한 데이터만 불러옵니다" in html
    assert "내 공간" not in html.split("</head>", 1)[1].replace(page["description"], "")
    assert "/api/member/dashboard" not in html


def test_feature_detail_page_copy_per_slug():
    research = render_feature_detail_page("research", site_base_url="https://example.com")
    member = render_feature_detail_page("member-workspace", site_base_url="https://example.com")
    outcomes = render_feature_detail_page("outcomes", site_base_url="https://example.com")
    methodology = render_feature_detail_page("methodology", site_base_url="https://example.com")

    assert "가격·출처·AI 의견을 한 화면에서 봅니다" in research
    assert "검색 후 바로 읽을 수 있습니다" in research
    assert "가입 후 저장" in research
    assert 'href="/features/member-workspace">마이페이지 보기</a>' in research
    assert 'href="/stocks/005930">삼성전자 예시 보기</a>' in research

    assert "<title>마이페이지 | TradingAgents Korea</title>" in member
    assert 'href="/member?mode=signup">마이페이지 만들기</a>' in member
    assert 'href="/features/research">AI 리포트 먼저 보기</a>' in member
    assert "로그인 후에는 개인 기록만 따로 열립니다" in member

    assert "<title>검증 결과 | TradingAgents Korea</title>" in outcomes
    assert 'href="/outcomes">검증 결과 보기</a>' in outcomes
    assert 'href="/features/methodology">분석 기준 보기</a>' in outcomes
    assert "검증 결과는 추천 성과가 아니라 리포트 품질 기록입니다" in outcomes

    assert "출처, 기준일, 한계를 함께 확인합니다" in methodology
    assert "KRX 가격 · DART 공시 · Naver 뉴스" in methodology
    assert "실거래 주문 차단" in methodology
    assert "증권 계좌 주문 권한은 연결하지 않습니다" in methodology
    assert "출처·한계·성과를 함께 검증합니다" in methodology
    assert 'href="/features/outcomes">검증 결과 보기</a>' in methodology
    assert 'class="grid-cards"' in methodology  # six cards -> three columns


def test_feature_detail_page_rejects_unknown_slug():
    with pytest.raises(ValueError, match="Unknown feature page"):
        render_feature_detail_page("unknown")


@pytest.mark.parametrize("slug", list(POLICY_PAGES))
def test_policy_pages_render_legal_text_verbatim_on_shell(slug):
    page = POLICY_PAGES[slug]
    html = render_policy_page(slug, site_base_url="https://example.com")

    assert "<!doctype html>" in html
    assert '<body class="ds ' in html
    assert f"<title>{page['title']}</title>" in html
    assert f'<link rel="canonical" href="https://example.com{page["path"]}">' in html
    assert f'<meta name="description" content="{page["description"]}">' in html
    assert page["heading"] in html
    assert page["lead"] in html
    assert 'class="policy-doc"' in html
    assert ".policy-doc { max-width: 760px; font-size: 15px; line-height: 1.7;" in html
    for title, items in page["sections"]:
        assert title in html
        for item in items:
            assert item in html
    for title, copy in page["callouts"]:
        assert title in html
        assert copy in html
    for label, href, copy in page["next_actions"]:
        assert f'href="{href}"' in html
        assert label in html
        assert copy in html
    assert "다음으로 확인할 화면" in html
    assert "정책을 읽은 뒤 실제 서비스 흐름으로 이어갑니다" in html
    assert "실거래 주문 기능을 제공하지 않는 주문 없는 AI 리서치 플랫폼" in html
    assert 'href="/features/methodology"' in html
    assert 'href="/mypage"' in html
    assert "rating/action" not in html
    assert "/api/member/dashboard" not in html
    assert "/api/portfolios" not in html
    assert "/api/watchlists" not in html
    assert 'name="robots"' not in html


def test_policy_page_headings():
    assert "개인정보는 기록과 인증에 필요한 만큼만 다룹니다" in render_policy_page("privacy")
    assert "이 서비스는 투자 실행이 아닌 근거 확인을 돕습니다" in render_policy_page("terms")
    assert "AI 리포트는 투자 조언이 아니라 검토 자료입니다" in render_policy_page("disclaimer")


def test_policy_page_rejects_unknown_slug():
    with pytest.raises(ValueError, match="Unknown policy page"):
        render_policy_page("unknown")


def test_info_pages_without_site_base_url_use_relative_canonical():
    assert '<link rel="canonical" href="/features">' in render_feature_index_page()
    assert '<link rel="canonical" href="/features/research">' in render_feature_detail_page("research")
    assert '<link rel="canonical" href="/terms">' in render_policy_page("terms")
