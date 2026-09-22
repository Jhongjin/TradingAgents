"""PER and PBR: either the limits can see something, or the page says they cannot."""

import pytest
from fastapi.testclient import TestClient

from tradingagents.site.api_app import create_app

from tradingagents.screener.screener import ScreenerConfig, _attach_valuations, screen_korean_market
from tradingagents.screener.universe import MarketSnapshot, MarketSnapshotRow
from tradingagents.screener.valuations import fetch_valuations, parse_valuation


def _integration(per="11.25배", pbr="2.91배", yield_="0.67%") -> dict:
    return {
        "itemCode": "005930",
        "totalInfos": [
            {"code": "marketValue", "key": "시총", "value": "1,465조 9,544억"},
            {"code": "per", "key": "PER", "value": per},
            {"code": "eps", "key": "EPS", "value": "22,292원"},
            {"code": "pbr", "key": "PBR", "value": pbr},
            {"code": "dividendYieldRatio", "key": "배당수익률", "value": yield_},
        ],
    }


def _row(code: str, **kwargs) -> MarketSnapshotRow:
    base = dict(name=f"종목{code}", market="KOSPI", close=50_000.0, volume=100_000.0,
                trading_value=5e9, market_cap=5e11, change_rate=0.01)
    base.update(kwargs)
    return MarketSnapshotRow(code=code, **base)


def test_the_ratios_come_out_of_the_units_they_are_printed_in():
    ratios = parse_valuation(_integration())
    assert ratios == {"per": 11.25, "pbr": 2.91, "dividend_yield": 0.67}


def test_a_dash_or_a_blank_is_not_a_number():
    assert parse_valuation(_integration(per="-", pbr="N/A")) == {"dividend_yield": 0.67}
    assert parse_valuation({}) == {}
    assert parse_valuation({"totalInfos": None}) == {}


def test_a_loss_making_company_keeps_its_negative_per():
    assert parse_valuation(_integration(per="-8.40배"))["per"] == -8.40


def test_every_code_is_asked_and_the_ones_that_fail_are_simply_absent():
    asked = []

    def fetch(code):
        asked.append(code)
        if code == "000660":
            raise RuntimeError("naver said no")
        return _integration()

    ratios = fetch_valuations(["005930", "000660", "035720"], fetcher=fetch)

    assert sorted(asked) == ["000660", "005930", "035720"]
    assert set(ratios) == {"005930", "035720"}          # the failure is a gap, not a crash
    assert fetch_valuations([], fetcher=fetch) == {}


def test_what_a_row_already_knows_is_not_overwritten():
    rows = [_row("005930"), _row("000660", per=7.5)]
    filled, priced = _attach_valuations(rows, {"005930": {"per": 11.25, "pbr": 2.9}, "000660": {"per": 99.0}})

    assert filled[0].per == 11.25 and filled[0].pbr == 2.9
    assert filled[1].per == 7.5                          # the snapshot's own figure wins
    assert priced == 2


def test_with_no_lookup_at_all_nothing_is_priced():
    filled, priced = _attach_valuations([_row("005930"), _row("000660")], None)
    assert priced == 0 and all(row.per is None for row in filled)


def _screen(rows, valuations, **config_kwargs):
    from datetime import date, timedelta

    snapshot = MarketSnapshot(as_of_date="2026-09-15", markets=("KOSPI",), rows=rows, vendor="test")
    # a long enough rising series that the factors have something to score
    start = date(2026, 1, 1)
    history = [
        {"date": (start + timedelta(days=day)).isoformat(), "close": 40_000.0 + day * 50, "volume": 1000 + day}
        for day in range(200)
    ]
    return screen_korean_market(
        "2026-09-15",
        config=ScreenerConfig(markets=("KOSPI",), top_n=5, **config_kwargs),
        snapshot=snapshot,
        history_fetcher=lambda code, start, end: history,
        valuations=valuations,
    )


def test_the_page_says_when_the_limits_had_nothing_to_read():
    result = _screen([_row("005930"), _row("000660")], None)
    assert "PER·PBR 지표 없음: 밸류에이션 한도 미적용" in result.notes


def test_the_page_says_how_many_rows_the_limits_could_see():
    result = _screen([_row("005930"), _row("000660")], {"005930": {"per": 11.25}})
    assert "PER·PBR 한도 적용: 1/2종목에 지표 있음" in result.notes


def test_an_expensive_name_is_now_actually_excluded():
    rows = [_row("005930"), _row("000660")]
    kept = {row.code for row in _screen(rows, {"000660": {"per": 120.0}}, max_per=60.0).candidates}
    assert "000660" not in kept and "005930" in kept

    # and without the lookup it would have sailed through, which was the bug
    everything = {row.code for row in _screen(rows, None, max_per=60.0).candidates}
    assert everything == {"005930", "000660"}


def test_the_rules_the_account_trades_on_are_the_ones_the_walk_forward_kept():
    """A rule the account trades on should not drift without a decision."""

    from tradingagents.harness.pipeline import PipelineConfig
    from tradingagents.site.paper_rules import RULE_LABELS, format_rule

    config = PipelineConfig()
    # The variability filter is second in training and second on the held-out
    # year — the only setting near the top of both, which is the only ranking
    # a walk-forward supports.
    assert config.volatility_exclude_top_pct == 0.2
    # 10% / 15% since 2026-09-22. The 5% stop that ran before it was picked by
    # a walk-forward that read closing prices only, and a stop the live account
    # checks five times a day is not a rule a daily close can measure: the same
    # replay went from +169.6% to +19.0% once it read session lows. Re-run with
    # intraday exits, 5% placed 3rd in training and last of seven on the
    # held-out year (+6.6%); 10%/15% placed 1st and 2nd, with a smaller
    # drawdown (-18.9% vs -33.3%) and 460 trades against 970.
    # Evidence: results/walkforward/2026-09-22.json.
    assert config.stop_loss_pct == 0.10
    assert config.take_profit_pct == 0.15

    # and it is on the published rules card, so turning it on is visible and dated
    labelled = {key for key, _label, _unit in RULE_LABELS}
    assert "volatility_exclude_top_pct" in labelled
    assert format_rule("volatility_exclude_top_pct", 0.2) == "20%"


def test_the_harness_page_does_not_ship_transcripts_nobody_reads():
    """30KB of debate per decision was going out inside a page that never drew it."""

    from tradingagents.site.harness_pages import _without_transcripts

    payload = {
        "run": {"id": "abc"},
        "decisions": [
            {"ticker_code": "005930", "detail": {
                "confirmation": {"rating": "Overweight", "rationale": "짧은 이유", "raw": {"debate": {"turns": {"bull": "x" * 20_000}}}},
                "order": {"status": "filled"},
            }},
            {"ticker_code": "000660", "detail": {"confirmation": {"rating": "Neutral"}}},
        ],
    }

    trimmed = _without_transcripts(payload)
    first = trimmed["decisions"][0]["detail"]["confirmation"]

    assert "raw" not in first
    assert first["rating"] == "Overweight" and first["rationale"] == "짧은 이유"
    assert first["raw_available_at"] == "/api/harness/runs/latest"
    # a decision without a transcript is passed through untouched
    assert trimmed["decisions"][1]["detail"]["confirmation"] == {"rating": "Neutral"}
    # and the original is not mutated
    assert "raw" in payload["decisions"][0]["detail"]["confirmation"]


def _stock_payload(code: str, *, name: str | None = None, market: str = "KOSPI",
                   points: int = 2, analysis: str = "available") -> dict:
    return {
        "ticker": {"code": code, "name": name if name is not None else f"종목{code}", "market": market},
        "chart": {"point_count": points},
        "analysis": {"status": analysis},
        "notices": [],
    }


def test_a_code_that_belongs_to_nobody_is_not_a_page():
    from tradingagents.site.stock_page import nothing_is_listed_here

    # unresolvable: the code is its own name, no market, no prices, no report
    assert nothing_is_listed_here(_stock_payload("999999", name="999999", market="UNKNOWN",
                                                 points=0, analysis="missing"))

    # a real name always renders
    assert not nothing_is_listed_here(_stock_payload("005930", name="삼성전자"))

    # and so does an obscure one whose directory lookup failed but whose chart works
    assert not nothing_is_listed_here(_stock_payload("123456", name="123456", market="UNKNOWN",
                                                     points=180, analysis="missing"))
    # or one with no prices today but a stored report
    assert not nothing_is_listed_here(_stock_payload("123456", name="123456", market="UNKNOWN",
                                                     points=0, analysis="available"))


def test_the_route_turns_that_into_a_404(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.site.api_app.render_public_stock_page",
        lambda ticker, **kwargs: (_ for _ in ()).throw(LookupError(f"{ticker} is not listed")),
    )
    with TestClient(create_app(repo=None, load_repo_from_env=False)) as client:
        response = client.get("/stocks/999999")
    assert response.status_code == 404


def test_the_edge_redirects_a_trailing_slash_instead_of_losing_it():
    """/paper/ was a 404 at the edge: the rewrites match /paper exactly.

    The config schema refuses unknown keys, so the reason lives here.
    """

    import json
    from pathlib import Path

    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    assert config["trailingSlash"] is False
    assert not any(key.startswith("_") for key in config), "vercel.json 은 추가 속성을 거부합니다"


def test_a_chart_with_no_points_does_not_call_itself_available():
    """/api/stocks/999999 said available over zero points, which sends a caller looking."""

    from tradingagents.site.public_api import build_public_stock_payload

    payload = build_public_stock_payload("005930", include_chart=False, include_analysis=False)
    assert (payload.get("chart") or {}).get("status") in {"empty", "unavailable", "skipped", None}


def test_the_api_refuses_an_unlisted_code_like_the_page_does(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.site.api_app.build_public_stock_payload",
        lambda ticker, **kwargs: {
            "ticker": {"code": "999999", "name": "999999", "market": "UNKNOWN"},
            "chart": {"status": "empty", "point_count": 0},
            "analysis": {"status": "missing"},
        },
    )
    with TestClient(create_app(repo=None, load_repo_from_env=False)) as client:
        assert client.get("/api/stocks/999999").status_code == 404
        # asking for only part of the picture is not enough to call it absent
        assert client.get("/api/stocks/999999", params={"include_chart": "false"}).status_code == 200


def test_a_list_with_nothing_in_it_does_not_call_itself_available():
    """The 분석 사용 가능 badge sat over "아직 공개된 리포트가 없습니다"."""

    import inspect

    from tradingagents.site import analysis_api

    source = inspect.getsource(analysis_api)
    assert '"status": "available" if items else "empty"' in source
    assert '"status": "available" if rows else "empty"' in source


def test_the_account_says_when_it_was_worked_out():
    """The footer promises every number carries its source and its time."""

    from tradingagents.harness.paper_state import build_combined_account_payload

    payload = build_combined_account_payload(None)
    assert "generated_at" in payload and payload["generated_at"]
    assert "as_of_date" in payload
    assert payload["generated_at"].endswith("+09:00")     # 한국 시각


def test_an_empty_list_is_labelled_as_empty_not_as_unknown():
    from tradingagents.site.web_pages import _analysis_feed_status_label, _analysis_outcomes_status_label

    assert _analysis_feed_status_label("empty") == "아직 없음"
    assert _analysis_outcomes_status_label("empty") == "아직 없음"
    assert _analysis_feed_status_label("available") == "분석 사용 가능"


def test_the_curve_says_which_of_the_three_books_it_draws():
    """The tiles add three books; a chart ending at a third of that must say so."""

    from tradingagents.site.paper_account_page import _curve_card

    curve = {
        "points": [{"date": "2026-09-10", "equity": 50_000_000, "benchmark": 100.0},
                   {"date": "2026-09-11", "equity": 49_000_000, "benchmark": 99.0}],
        "summary": {"day_count": 2, "first_date": "2026-09-10", "account_return": -0.02,
                    "benchmark_return": -0.01, "excess_return": -0.01, "max_drawdown": -0.02,
                    "benchmark_name": "KOSPI"},
    }

    labelled = _curve_card(curve, account_label="AI 확인")
    assert "수익률 추이 · AI 확인 계좌" in labelled
    assert "AI 확인 계좌" in labelled
    assert "위 합계는 세 계좌를 더한 값이고, 이 곡선은 그중 한 계좌입니다." in labelled

    # and with nothing to say it falls back rather than printing an empty label
    plain = _curve_card(curve)
    assert "수익률 추이<" in plain.replace("</h2>", "<") or "수익률 추이" in plain
    assert "모의 계좌" in plain


def test_a_sharpe_from_three_days_is_not_printed():
    """Annualising a three-day sample produced -105.93 next to -1.68%."""

    from tradingagents.site.paper_account_page import MIN_RISK_DAYS, _curve_card

    summary = {"day_count": 3, "first_date": "2026-09-10", "account_return": -0.0168,
               "benchmark_return": -0.0497, "excess_return": 0.0329, "max_drawdown": -0.0148,
               "benchmark_name": "KOSPI",
               "risk": {"sharpe_ratio": -105.934062, "annualized_volatility": 0.0176}}

    thin = _curve_card({"points": [{"date": "d", "equity": 1, "benchmark": 1}] * 3, "summary": summary})
    assert "-105.93" not in thin and "105.934062" not in thin
    assert f"샤프·변동성은 {MIN_RISK_DAYS}일치가 쌓이면 표시합니다" in thin

    thick = _curve_card({"points": [{"date": "d", "equity": 1, "benchmark": 1}] * MIN_RISK_DAYS,
                         "summary": {**summary, "risk": {"sharpe_ratio": 1.199344, "annualized_volatility": 0.2431}}})
    assert "샤프 <b>1.20</b>" in thick          # two decimals, like everything beside it
    assert "변동성 <b>24.3%</b>" in thick       # a percentage, and unsigned


def test_a_missing_number_does_not_keep_its_unit():
    """The holdings table read "- -원" and the harness one "-주 기준가 -원"."""

    from tradingagents.site.harness_pages import _shares as harness_shares
    from tradingagents.site.harness_pages import _won as harness_won
    from tradingagents.site.paper_account_page import _shares, _won

    assert _won(None) == "-" and _won(0) == "0원" and _won(113_400) == "113,400원"
    assert _shares(None) == "-" and _shares(43) == "43주"
    assert harness_won(None) == "-" and harness_won(1000) == "1,000원"
    assert harness_shares(None) == "-" and harness_shares(76) == "76주"


def test_a_reader_is_not_shown_the_field_name_and_the_raw_ratio():
    """/stocks printed "drawdown_from_window_high: -0.3013" at a reader."""

    from tradingagents.site.web_pages import _lens_metric_bits

    bits = _lens_metric_bits({"drawdown_from_window_high": -0.3013, "annualized_volatility_20d": 0.6756})
    assert bits == "고점 대비 낙폭 -30.1% · 20일 연환산 변동성 67.6%"   # 변동성은 부호 없음
    assert "drawdown_from_window_high" not in bits

    assert _lens_metric_bits({"volume_ratio": 0.235}) == "거래량 배수 0.23배"
    assert _lens_metric_bits({"live_trading": "disabled"}) == "실거래 disabled"
    assert _lens_metric_bits({}) == ""


def test_a_run_with_no_ai_says_so_instead_of_printing_a_dash():
    """The alert read "DL이앤씨 — - · 모의 1주", which looks like a bug, not a fact."""

    from tradingagents.site.notifications import compose_issue_messages

    rules_only = {
        "run": {"id": "abc", "as_of_date": "2026-09-16", "confirmer": "none"},
        "decisions": [{"ticker_code": "375500", "ticker_name": "DL이앤씨", "stage": "ordered", "quantity": 1}],
    }
    body = compose_issue_messages(rules_only, issue_number=43, site_base_url="https://agenttrust.kr")["paid"]

    assert "DL이앤씨 — 규칙 통과 · 모의 1주" in body
    assert "— -" not in body
    assert "선별 기록: https://agenttrust.kr/harness/abc" in body
    assert "토론 전문" not in body               # there was no argument to read

    argued = {
        "run": {"id": "abc", "as_of_date": "2026-09-16", "confirmer": "debate"},
        "decisions": [{"ticker_code": "375500", "ticker_name": "DL이앤씨", "stage": "ordered", "quantity": 1,
                       "confirmation_rating": "Overweight", "confirmation_confidence": 0.76}],
    }
    debated = compose_issue_messages(argued, issue_number=44, site_base_url="https://agenttrust.kr")["paid"]
    assert "DL이앤씨 — Overweight 0.76 · 모의 1주" in debated
    assert "토론 전문: https://agenttrust.kr/harness/abc" in debated
