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


def test_the_rule_change_of_2026_09_15_is_pinned_and_published():
    """A rule the account trades on should not drift without a decision."""

    from tradingagents.harness.pipeline import PipelineConfig
    from tradingagents.site.paper_rules import RULE_LABELS, format_rule

    config = PipelineConfig()
    # measured over the three years to 2026-09-15: +52.2% -> +129.7%, drawdown
    # -28.7% -> -24.2%, hit rate 39.3% -> 47.9%
    assert config.volatility_exclude_top_pct == 0.2
    assert config.stop_loss_pct == 0.08

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
    import json
    from pathlib import Path

    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    assert config["trailingSlash"] is False
