import pandas as pd
import pytest

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.screener import (
    MarketSnapshot,
    MarketSnapshotRow,
    ScreenerConfig,
    compute_factor_scores,
    load_market_snapshot,
    screen_korean_market,
)


def _points(count=200, *, drift=0.004, start=10_000.0, volume=1_000_000):
    rows = []
    close = start
    for index in range(count):
        close = close * (1 + drift)
        rows.append({"date": f"2026-{(index // 28) % 12 + 1:02d}-{index % 28 + 1:02d}", "close": round(close, 2), "volume": volume})
    return rows


def _row(code, name, market="KOSPI", **overrides):
    base = dict(
        code=code,
        name=name,
        market=market,
        close=50_000.0,
        volume=2_000_000.0,
        trading_value=50_000_000_000.0,
        market_cap=5_000_000_000_000.0,
        change_rate=0.5,
        per=15.0,
        pbr=1.5,
        dividend_yield=1.0,
    )
    base.update(overrides)
    return MarketSnapshotRow(**base)


def test_factor_scores_flag_uptrend_and_breakout():
    scores = compute_factor_scores(_points())
    assert scores.momentum_20d > 0
    assert scores.ma_alignment == pytest.approx(1.0)
    assert scores.composite > 0
    assert "정배열 상승추세" in scores.labels
    assert "60일 고점 근접" in scores.labels


def test_factor_scores_handle_short_history():
    scores = compute_factor_scores(_points(10))
    assert scores.momentum_20d is None
    assert scores.labels == ["가격 이력 부족"]


def test_screener_prefilters_and_ranks_candidates():
    snapshot = MarketSnapshot(
        as_of_date="2026-09-05",
        markets=("KOSPI", "KOSDAQ"),
        rows=[
            _row("005930", "삼성전자"),
            _row("000660", "SK하이닉스", per=8.0, pbr=0.9, dividend_yield=3.5),
            _row("999999", "초소형주", market_cap=10_000_000_000.0),
            _row("888888", "고평가주", per=150.0),
            _row("777777", "저유동성", trading_value=100_000_000.0),
        ],
    )
    histories = {
        "005930": _points(drift=0.002),
        "000660": _points(drift=0.006),
    }

    def fetcher(code, start, end):
        if code not in histories:
            raise VendorUnavailableError(code)
        return histories[code]

    result = screen_korean_market(snapshot=snapshot, history_fetcher=fetcher, config=ScreenerConfig(top_n=5))

    assert result.universe_size == 5
    assert result.prefiltered_size == 2
    codes = [candidate.code for candidate in result.candidates]
    assert codes == ["000660", "005930"]
    top = result.candidates[0]
    assert top.rank == 1
    assert "PER 8.0 저평가 구간" in top.reasons
    assert "배당수익률 3.5%" in top.reasons
    payload = result.as_dict()
    assert payload["execution_boundary"] == "screening_only_no_orders"
    assert payload["candidates"][0]["factors"]["composite"] >= payload["candidates"][1]["factors"]["composite"]


def test_screener_respects_min_composite_and_top_n():
    snapshot = MarketSnapshot(as_of_date="2026-09-05", markets=("KOSPI",), rows=[_row("005930", "삼성전자"), _row("000660", "SK하이닉스")])
    result = screen_korean_market(
        snapshot=snapshot,
        history_fetcher=lambda code, s, e: _points(drift=-0.004),
        config=ScreenerConfig(top_n=1, min_composite=0.0),
    )
    assert result.candidates == []
    result = screen_korean_market(
        snapshot=snapshot,
        history_fetcher=lambda code, s, e: _points(drift=0.004),
        config=ScreenerConfig(top_n=1),
    )
    assert len(result.candidates) == 1


def test_screener_config_validation():
    with pytest.raises(ValueError):
        ScreenerConfig(top_n=0)
    with pytest.raises(ValueError):
        ScreenerConfig(history_days=5)


def test_load_market_snapshot_uses_injected_frames_and_walks_back_holidays():
    calls = []

    def ohlcv(compact_date, market):
        calls.append((compact_date, market))
        if compact_date == "20260906":
            return pd.DataFrame()
        return pd.DataFrame(
            {"시가": [100], "고가": [110], "저가": [90], "종가": [105], "거래량": [1000], "거래대금": [105_000], "등락률": [1.0]},
            index=["5930"],
        )

    def caps(compact_date, market):
        return pd.DataFrame({"시가총액": [4e14]}, index=["005930"])

    def fundamentals(compact_date, market):
        return pd.DataFrame({"PER": [12.0], "PBR": [1.1], "DIV": [2.5]}, index=["005930"])

    snapshot = load_market_snapshot(
        "2026-09-06",
        markets=("KOSPI",),
        ohlcv_fetcher=ohlcv,
        cap_fetcher=caps,
        fundamental_fetcher=fundamentals,
        name_lookup=lambda code: "삼성전자",
    )

    assert snapshot.as_of_date == "2026-09-05"
    assert calls[0] == ("20260906", "KOSPI")
    row = snapshot.rows[0]
    assert row.code == "005930"
    assert row.name == "삼성전자"
    assert row.market_cap == 4e14
    assert row.per == 12.0
    assert row.dividend_yield == 2.5


def test_load_market_snapshot_raises_when_no_rows():
    def failing(d, m):
        raise ConnectionError("certificate verify failed")

    with pytest.raises(VendorUnavailableError, match="certificate verify failed"):
        load_market_snapshot(
            "2026-09-06",
            markets=("KOSDAQ",),
            ohlcv_fetcher=failing,
            cap_fetcher=lambda d, m: pd.DataFrame(),
            fundamental_fetcher=lambda d, m: pd.DataFrame(),
            name_lookup=lambda code: code,
            lookback_business_days=1,
        )
    with pytest.raises(VendorUnavailableError):
        load_market_snapshot(
            "2026-09-06",
            markets=("KOSDAQ",),
            ohlcv_fetcher=lambda d, m: pd.DataFrame(),
            cap_fetcher=lambda d, m: pd.DataFrame(),
            fundamental_fetcher=lambda d, m: pd.DataFrame(),
            name_lookup=lambda code: code,
            lookback_business_days=1,
        )


def test_screener_falls_back_to_bounded_universe_when_snapshot_blocked(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_SCREENER_UNIVERSE", "005930,000660.KS,bogus")

    def blocked(when, markets):
        raise VendorUnavailableError("data.krx.co.kr blocked")

    histories = {"005930": _points(drift=0.002), "000660": _points(drift=0.005)}
    result = screen_korean_market(
        "2026-09-05",
        config=ScreenerConfig(top_n=5),
        snapshot_loader=blocked,
        history_fetcher=lambda code, s, e: histories[code],
    )

    assert [candidate.code for candidate in result.candidates] == ["000660", "005930"]
    assert result.candidates[0].market_cap is None
    assert any("fallback universe of 2 tickers" in note for note in result.notes)
    assert any("history_fallback" in note for note in result.notes)

    with pytest.raises(VendorUnavailableError):
        screen_korean_market(
            "2026-09-05",
            config=ScreenerConfig(top_n=5, allow_fallback_universe=False),
            snapshot_loader=blocked,
            history_fetcher=lambda code, s, e: histories[code],
        )


def test_fallback_universe_codes_precedence(monkeypatch):
    from tradingagents.screener import fallback_universe_codes

    monkeypatch.delenv("TRADINGAGENTS_SCREENER_UNIVERSE", raising=False)
    monkeypatch.setenv("TRADINGAGENTS_SITEMAP_TICKERS", "035420,035420,000660")
    assert fallback_universe_codes() == ("035420", "000660")
    monkeypatch.delenv("TRADINGAGENTS_SITEMAP_TICKERS", raising=False)
    assert "005930" in fallback_universe_codes()


def test_load_market_snapshot_rejects_unknown_market():
    with pytest.raises(ValueError):
        load_market_snapshot("2026-09-05", markets=("NASDAQ",), ohlcv_fetcher=lambda d, m: pd.DataFrame())
