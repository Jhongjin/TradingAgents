import json
import re
from datetime import date

import pytest

from tradingagents.site.analysis_pages import (
    render_public_analysis_detail_page,
    render_public_analysis_feed_page,
    render_public_outcomes_page,
)
from tradingagents.storage import (
    AgentReportInput,
    AnalysisOutcomeInput,
    AnalysisRunInput,
    StorageRepository,
    TradeDecisionInput,
    create_storage_engine,
)

FLAGGED_TERMS = ("하네스", "유니버스", "깔때기", "요인 점수", "가상 주문", "가상 매수", "채점", "감사 원장", "판정관", "리스크 패널", "내 공간", "사후 결과", "원문 데이터", "종목 분석실", "알파")


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def _seed(repo: StorageRepository, *, name: str = "삼성전자", report_title: str = "Market report", rationale: str = "현금흐름과 수급을 추가 확인합니다.") -> str:
    run_id = repo.create_analysis_run(
        AnalysisRunInput(
            ticker_code="005930",
            ticker_name=name,
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            visibility="public",
            model_provider="openai",
            deep_model="deep",
            quick_model="quick",
            metadata={
                "source": "trading_graph",
                "currency": "KRW",
                "output_language": "ko-KR",
                "selected_analysts": ["market", "news", "fundamentals"],
            },
        )
    )
    repo.add_agent_report(AgentReportInput(analysis_run_id=run_id, role="market", title=report_title, content="market report body\nsecond paragraph"))
    repo.record_trade_decision(TradeDecisionInput(analysis_run_id=run_id, rating="Hold", action="hold", rationale=rationale, raw_decision="Rating: Hold"))
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            ticker_name=name,
            market="KOSPI",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=5,
            actual_holding_days=5,
            status="completed",
            raw_return=0.04,
            benchmark_return=0.01,
            alpha_return=0.03,
            decision_rating="Hold",
            decision_action="hold",
        )
    )
    repo.upsert_analysis_outcome(
        AnalysisOutcomeInput(
            analysis_run_id=run_id,
            ticker_code="005930",
            trade_date=date(2026, 5, 5),
            evaluated_at=date(2026, 5, 12),
            horizon_days=20,
            actual_holding_days=3,
            status="pending",
        )
    )
    repo.complete_analysis_run(run_id)
    return run_id


def _json_ld_blocks(html: str) -> list[dict]:
    return [json.loads(match.group(1)) for match in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def _assert_shell(html: str, *, active: str) -> None:
    assert html.startswith("<!doctype html>")
    assert 'class="ds ' in html
    assert 'id="main-content"' in html
    assert f'<a href="{active}" aria-current="page">' in html
    assert "PAGE_CSS" not in html
    assert "syncTopAuthLinks" not in html
    assert "resolveTickerInput" not in html
    # Copy rules apply to the visible page; the JSON payload and the legacy JSON-LD
    # builder (kept verbatim from web_pages) are excluded from the check.
    visible = re.sub(r'<script[^>]*type="application/(?:ld\+json|json)"[^>]*>.*?</script>', "", html, flags=re.S)
    for term in FLAGGED_TERMS:
        assert term not in visible, term


# --- /analyses ---------------------------------------------------------------------------
def test_feed_page_lists_completed_runs_on_design_system():
    repo = _repo()
    run_id = _seed(repo)

    html = render_public_analysis_feed_page(repo=repo, site_base_url="https://example.com")

    _assert_shell(html, active="/analyses")
    assert "<title>AI 리포트 | TradingAgents Korea</title>" in html
    assert '<link rel="canonical" href="https://example.com/analyses">' in html
    assert '<meta name="robots"' not in html
    assert "<h1>AI 리포트</h1>" in html
    assert "TradingAgents Korea가 공개한 한국 주식 AI 분석 리포트 목록입니다." in html
    # filter form keeps the GET contract
    assert '<form class="an-filter" action="/analyses" method="get"' in html
    assert 'name="ticker"' in html
    assert 'id="analysisTicker"' in html
    # stat tiles and summary
    assert "완료 리포트" in html
    assert "최근 20건 기준" in html
    assert "대상 종목" in html
    assert "평균 초과수익" in html
    assert "KOSPI 1" in html
    assert "보유 관찰 1" in html
    assert "검증 완료 1건" in html
    # row content
    assert "삼성전자" in html
    assert "5거래일 초과수익" in html
    assert '<span class="num up">+3.00%</span>' in html
    assert "종목 +4.00% · 시장 +1.00%" in html
    assert "보유 관찰" in html
    assert f'href="/analyses/{run_id}">리포트 상세</a>' in html
    assert 'href="/stocks/005930">종목 분석</a>' in html
    assert 'href="/outcomes?ticker=005930">검증 결과</a>' in html
    assert f'href="/api/analyses/{run_id}">JSON 데이터</a>' in html
    assert 'id="analysis-feed-payload" type="application/json"' in html
    # the shell emits og/twitter meta once; the page must not duplicate it
    assert html.count('property="og:title"') == 1


def test_feed_page_ticker_filter_and_empty_state():
    html = render_public_analysis_feed_page(repo=_repo(), ticker="005930", site_base_url="https://example.com")

    _assert_shell(html, active="/analyses")
    assert "<h1>005930 AI 리포트</h1>" in html
    assert 'value="005930"' in html
    assert "005930 필터 적용" in html
    assert "결과 0건" in html
    assert "005930 리포트가 아직 없습니다" in html
    assert 'href="/analyses">필터 초기화</a>' in html
    assert 'href="/stocks/005930">종목 분석</a>' in html
    assert 'href="/outcomes?ticker=005930">검증 결과</a>' in html
    assert 'href="/member?mode=signup&amp;tab=analysis#analysis-request-section">분석 요청</a>' in html
    assert "성과 검증 요약" not in html


def test_feed_page_without_repo_shows_global_empty_state():
    html = render_public_analysis_feed_page(repo=None)

    _assert_shell(html, active="/analyses")
    assert "아직 공개된 AI 리포트가 없습니다" in html
    assert 'href="/stocks/005930">삼성전자 종목 분석</a>' in html
    assert 'href="/features/methodology">분석 기준</a>' in html
    assert "목록 대기" in html


def test_feed_page_escapes_user_data():
    repo = _repo()
    _seed(repo, name='삼성전자 <script>alert("x")</script>')

    html = render_public_analysis_feed_page(repo=repo)

    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    payload_json = re.search(r'<script id="analysis-feed-payload" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert "<" not in payload_json and ">" not in payload_json
    assert "\\u003cscript\\u003e" in payload_json


# --- /outcomes ---------------------------------------------------------------------------
def test_outcomes_page_lists_verification_rows():
    repo = _repo()
    run_id = _seed(repo)

    html = render_public_outcomes_page(repo=repo, site_base_url="https://example.com")

    _assert_shell(html, active="/outcomes")
    assert "<title>리포트 성과 검증 | TradingAgents Korea</title>" in html
    assert '<link rel="canonical" href="https://example.com/outcomes">' in html
    assert "<h1>리포트 성과 검증</h1>" in html
    assert "AI 리포트가 나온 뒤 5거래일과 20거래일 수익률을 같은 기간 시장 지수와 비교한 검증 결과 목록입니다." in html
    assert '<form class="an-filter" action="/outcomes" method="get"' in html
    assert 'id="outcomeTicker"' in html and 'name="ticker"' in html
    assert 'id="outcomeStatus"' in html and 'name="status"' in html
    assert '<option value="completed">검증 완료</option>' in html
    assert '<option value="pending">검증 대기</option>' in html
    # tiles
    assert "검증 완료" in html
    assert "초과수익 양수 비율" in html
    assert "종목 평균 수익률 +4.00%" in html
    assert "검증 대기 / 데이터 없음" in html
    assert "1 / 0" in html
    # rows (completed and pending)
    assert "5거래일 수익률 +4.00%, 초과수익 +3.00% (2026-05-12 기준)" in html
    assert "3거래일만 지나 20거래일 검증을 기다립니다." in html
    assert '<span class="num up">+3.00%</span>' in html
    assert '<span class="badge b-teal">검증 완료</span>' in html
    assert '<span class="badge b-amber">검증 대기</span>' in html
    assert f'href="/analyses/{run_id}">리포트 상세</a>' in html
    assert 'href="/stocks/005930">종목 분석</a>' in html
    assert 'href="/analyses?ticker=005930">같은 종목 리포트</a>' in html
    assert 'href="/api/analysis-outcomes?limit=20">JSON 데이터</a>' in html
    assert 'id="outcomes-payload" type="application/json"' in html
    assert "검증은 이렇게 계산합니다" in html


def test_outcomes_page_filters_keep_query_names_and_selected_state():
    repo = _repo()
    _seed(repo)

    html = render_public_outcomes_page(repo=repo, ticker="005930", status="completed", site_base_url="https://example.com")

    _assert_shell(html, active="/outcomes")
    assert 'value="005930"' in html
    assert '<option value="completed" selected>검증 완료</option>' in html
    assert "005930 / 완료 적용" in html
    assert "결과 1건" in html
    assert "검증 대기</span>" not in html.split("<tbody>")[1].split("</tbody>")[0]  # pending row filtered out
    assert 'href="/api/analysis-outcomes?limit=20&amp;ticker=005930&amp;status=completed">JSON 데이터</a>' in html


def test_outcomes_page_filtered_empty_state_and_global_empty_state():
    filtered = render_public_outcomes_page(repo=_repo(), ticker="005930", status="completed", site_base_url="https://example.com")
    assert "005930 검증 완료 검증 결과가 없습니다" in filtered
    assert 'href="/outcomes">필터 초기화</a>' in filtered
    assert 'href="/analyses?ticker=005930">AI 리포트</a>' in filtered
    assert 'href="/stocks/005930">종목 분석</a>' in filtered

    empty = render_public_outcomes_page(repo=None)
    _assert_shell(empty, active="/outcomes")
    assert "아직 검증 결과가 없습니다" in empty
    assert 'href="/stocks/005930#analysis-outcomes">삼성전자 검증 결과</a>' in empty
    assert 'href="/features/outcomes">계산 기준</a>' in empty
    assert "결과 0건" not in empty


def test_outcomes_page_escapes_user_data():
    repo = _repo()
    _seed(repo, name="삼성전자 <img src=x onerror=alert(1)>")

    html = render_public_outcomes_page(repo=repo)

    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


# --- /analyses/{id} ----------------------------------------------------------------------
def test_detail_page_shows_report_context_and_json_ld():
    repo = _repo()
    run_id = _seed(repo)

    html = render_public_analysis_detail_page(run_id, repo=repo, site_base_url="https://example.com")

    _assert_shell(html, active="/analyses")
    assert "<title>삼성전자 005930 공개 분석 리포트 | TradingAgents Korea</title>" in html
    assert f'<link rel="canonical" href="https://example.com/analyses/{run_id}">' in html
    assert '<meta property="og:type" content="article">' in html
    assert "<h1>삼성전자 공개 분석 리포트</h1>" in html
    assert "2026-05-05 기준 삼성전자(005930) AI 분석 리포트입니다. AI 의견은 보유 관찰이고, 리포트 1개와 검증 결과 1건을 담았습니다." in html
    assert 'content="2026-05-05 기준 삼성전자(005930) AI 분석 리포트입니다. AI 의견 보유 관찰, 리포트 1개, 검증 결과 1건."' in html
    # section anchors and tabs
    for anchor in ("analysis-decision", "analysis-reports", "analysis-outcomes", "analysis-provenance"):
        assert f'id="{anchor}"' in html
        assert f'href="#{anchor}"' in html
    # decision
    assert "AI 의견 보유 관찰" in html
    assert "현금흐름과 수급을 추가 확인합니다." in html
    assert "<span>보유 관찰</span>" in html
    # reports
    assert "Market report" in html
    assert '<span class="badge b-violet">시장 분석</span>' in html
    assert "<p>market report body</p>" in html
    assert "근거 점검" in html
    # outcomes table
    assert "5거래일 수익률 +4.00%, 초과수익 +3.00% (2026-05-12 기준)" in html
    assert '<span class="badge b-amber">검증 대기</span>' in html
    # provenance
    assert "KRX · DART · Naver" in html
    assert "market, news, fundamentals" in html
    assert "생성 경로 trading_graph / 통화 KRW / 언어 ko-KR" in html
    assert "휴장, 제공처 장애, 누락 데이터, 모델 오류 가능성" in html
    assert run_id in html
    # links
    assert 'href="/stocks/005930">' in html
    assert 'href="/outcomes?ticker=005930">' in html
    assert f'href="/api/analyses/{run_id}">JSON 데이터</a>' in html
    assert 'href="/member?mode=signup&amp;tab=analysis#analysis-request-section"' in html
    assert 'id="analysis-detail-payload" type="application/json"' in html
    # JSON-LD: the page Article block is emitted next to the shell's site graph
    blocks = _json_ld_blocks(html)
    article = [block for block in blocks if block.get("@type") == "Article"]
    assert len(article) == 1
    assert article[0]["headline"] == "삼성전자 공개 분석 리포트"
    assert article[0]["url"] == f"https://example.com/analyses/{run_id}"
    assert article[0]["about"] == {"@type": "Thing", "name": "삼성전자", "identifier": "005930", "additionalType": "KoreanStock"}
    assert article[0]["publisher"] == {"@type": "Organization", "name": "TradingAgents Korea"}


def test_detail_page_missing_sections_have_recovery_actions():
    repo = _repo()
    run_id = repo.create_analysis_run(
        AnalysisRunInput(ticker_code="005930", ticker_name="삼성전자", market="KOSPI", trade_date=date(2026, 5, 5), visibility="public", model_provider="openai")
    )
    repo.complete_analysis_run(run_id)

    html = render_public_analysis_detail_page(run_id, repo=repo, site_base_url="https://example.com")

    _assert_shell(html, active="/analyses")
    assert "아직 저장된 AI 의견이 없습니다" in html
    assert "아직 저장된 리포트가 없습니다" in html
    assert "검증 대기" in html
    assert html.count(f'href="/api/analyses/{run_id}">JSON 데이터</a>') >= 2
    assert 'href="/stocks/005930">종목 분석</a>' in html
    assert 'href="/member?mode=signup&amp;tab=analysis#analysis-request-section">새 분석 요청</a>' in html


def test_detail_page_escapes_report_and_decision_text():
    repo = _repo()
    run_id = _seed(repo, name="삼성전자 <b>x</b>", report_title='Report <script>alert("r")</script>', rationale="근거 <img src=x onerror=alert(1)>")

    html = render_public_analysis_detail_page(run_id, repo=repo, site_base_url="https://example.com")

    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    # JSON-LD and payload scripts must not be closable by injected markup
    for match in re.finditer(r'<script type="application/(?:ld\+json|json)"[^>]*>(.*?)</script>', html, re.S):
        assert "</script" not in match.group(1)
    article = [block for block in _json_ld_blocks(html) if block.get("@type") == "Article"][0]
    assert article["about"]["name"] == "삼성전자 <b>x</b>"


def test_detail_page_rejects_unknown_or_private_runs():
    repo = _repo()
    with pytest.raises(ValueError):
        render_public_analysis_detail_page("00000000-0000-0000-0000-000000000000", repo=repo)
    with pytest.raises(ValueError):
        render_public_analysis_detail_page("00000000-0000-0000-0000-000000000000", repo=None)
    private_id = repo.create_analysis_run(
        AnalysisRunInput(ticker_code="005930", ticker_name="삼성전자", market="KOSPI", trade_date=date(2026, 5, 5), visibility="private", model_provider="openai")
    )
    repo.complete_analysis_run(private_id)
    with pytest.raises(ValueError):
        render_public_analysis_detail_page(private_id, repo=repo)
