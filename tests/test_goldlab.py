"""The gold pattern lab: detectors count, the study compares with doing nothing."""

import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from goldlab.contracts import GOLD_FUTURES, MICRO_GOLD_FUTURES
from goldlab.data import bars_from_rows, resample
from goldlab.patterns import PATTERN_REGISTRY, detect_patterns
from goldlab.patterns.structure import find_pivots
from goldlab.study import base_rates, run_pattern_study


def _bar(stamp, open_, high, low, close, volume=1000.0):
    return {"timestamp": stamp, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


def _synthetic(bars: int = 3000, seed: int = 3):
    rng = random.Random(seed)
    rows, price, stamp = [], 2400.0, datetime(2025, 1, 1, tzinfo=timezone.utc)
    for step in range(bars):
        stamp += timedelta(hours=1)
        drift = 0.0002 if (step // 200) % 2 == 0 else -0.0002
        price *= 1 + drift + rng.uniform(-0.004, 0.004)
        high = price * (1 + abs(rng.gauss(0, 0.002)))
        low = price * (1 - abs(rng.gauss(0, 0.002)))
        rows.append(_bar(stamp, round(low + (high - low) * rng.random(), 1), round(high, 1), round(low, 1), round(price, 1), 1000 + step))
    return bars_from_rows(rows, symbol="GC=F", interval="1h")


def test_contract_maths_is_in_money_not_percent():
    # gold moves one dollar, one contract of 100 ounces moves one hundred
    gross = GOLD_FUTURES.pnl(2400.0, 2401.0, contracts=1, long=True)
    assert 60 < gross < 100  # a dollar, less two-sided slippage and commission
    assert GOLD_FUTURES.tick_value == pytest.approx(10.0)
    assert MICRO_GOLD_FUTURES.tick_value == pytest.approx(1.0)
    assert GOLD_FUTURES.pnl(2400.0, 2399.0, long=True) < 0
    assert GOLD_FUTURES.pnl(2400.0, 2399.0, long=False) > 0
    assert GOLD_FUTURES.round_to_tick(2400.037) == pytest.approx(2400.0)
    assert GOLD_FUTURES.contracts_for_risk(risk_amount=1000, entry=2400.0, stop=2395.0) == 2
    assert GOLD_FUTURES.contracts_for_risk(risk_amount=1000, entry=2400.0, stop=2400.0) == 0


def test_every_registered_pattern_runs_and_dates_its_hits():
    series = _synthetic()
    hits = detect_patterns(series)
    assert len(PATTERN_REGISTRY) >= 20
    assert hits and all(0 <= hit.index < len(series) for hit in hits)
    assert all(hit.timestamp == series.bars[hit.index].timestamp for hit in hits)
    assert hits == sorted(hits, key=lambda hit: (hit.index, hit.pattern))
    assert {hit.direction for hit in hits} <= {"bullish", "bearish"}


def test_a_hand_drawn_engulfing_is_found():
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 2500.0
    for step in range(12):  # a decline, so the pattern has a trend to reverse
        price -= 3
        rows.append(_bar(stamp + timedelta(hours=step), price + 1, price + 2, price - 2, price))
    rows.append(_bar(stamp + timedelta(hours=12), price, price + 1, price - 6, price - 5))      # down bar
    rows.append(_bar(stamp + timedelta(hours=13), price - 6, price + 4, price - 7, price + 3))  # engulfs it
    series = bars_from_rows(rows, symbol="GC=F", interval="1h")

    hits = detect_patterns(series, patterns=["bullish_engulfing"])
    assert [hit.index for hit in hits] == [13]
    assert hits[0].direction == "bullish" and hits[0].label == "상승 장악형"


def test_pivots_sit_on_the_turns():
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    shape = [10, 11, 12, 15, 12, 11, 10, 9, 8, 5, 8, 9, 10, 11, 12]
    rows = [_bar(stamp + timedelta(hours=index), value, value + 0.5, value - 0.5, value) for index, value in enumerate(shape)]
    series = bars_from_rows(rows, symbol="GC=F", interval="1h")

    pivots = find_pivots(series.bars, span=3)
    kinds = {pivot.index: pivot.kind for pivot in pivots}
    assert kinds.get(3) == "high"  # the peak at 15
    assert kinds.get(9) == "low"   # the trough at 5


def test_resampling_keeps_the_true_high_and_low():
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [_bar(stamp + timedelta(hours=index), 100 + index, 110 + index, 90 + index, 105 + index) for index in range(8)]
    series = bars_from_rows(rows, symbol="GC=F", interval="1h")

    four_hour = resample(series, factor=4, interval="4h")
    assert len(four_hour) == 2
    first = four_hour.bars[0]
    assert first.open == 100 and first.close == 108
    assert first.high == max(row["high"] for row in rows[:4])
    assert first.low == min(row["low"] for row in rows[:4])
    assert first.volume == sum(row["volume"] for row in rows[:4])


def test_the_study_reports_the_edge_over_doing_nothing():
    series = _synthetic()
    result = run_pattern_study(series, horizons=(4, 12), min_occurrences=20, contract=GOLD_FUTURES)

    assert result.bars == len(series) and result.horizons == (4, 12)
    assert result.base_rate[12]["long"]["count"] > 1000
    assert 0 < result.base_rate[12]["long"]["win_rate"] < 1

    measured = [row for row in result.patterns if (row["horizons"].get("12") or {}).get("count")]
    assert measured
    for row in measured:
        stats = row["horizons"]["12"]
        assert "edge_win_rate" in stats and "edge_return" in stats
        # the edge is the pattern minus the base rate, not the raw number
        assert stats["edge_return"] == pytest.approx(stats["average_return"] - stats["base_average_return"], abs=1e-9)
        assert stats["average_mae"] <= 0 <= stats["average_mfe"]
        assert isinstance(stats["enough_samples"], bool)
    assert any("기준 대비" in note for note in result.notes)


def test_a_short_pattern_is_measured_short():
    series = _synthetic()
    result = run_pattern_study(series, horizons=(12,), min_occurrences=5)
    bearish = next((row for row in result.patterns if row["direction"] == "bearish" and (row["horizons"].get("12") or {}).get("count")), None)
    assert bearish is not None
    short_base = result.base_rate[12]["short"]
    assert short_base["count"] > 0
    # a falling market is a win for a short, so the two base rates disagree
    assert short_base["win_rate"] != result.base_rate[12]["long"]["win_rate"]


def test_too_few_bars_is_refused():
    series = _synthetic(bars=40)
    with pytest.raises(ValueError):
        run_pattern_study(series, horizons=(72,))


def test_base_rate_counts_every_bar_it_can():
    series = _synthetic(bars=500)
    rates = base_rates(series.bars, (10,))
    assert rates[10]["count"] == len(series) - 10


def _stub_study(monkeypatch, stats: dict) -> None:
    from goldlab import live

    monkeypatch.setattr(live, "ensure_study", lambda *args, **kwargs: stats)


def test_the_live_scan_quotes_the_record_beside_what_just_formed(monkeypatch, tmp_path):
    from goldlab import live

    series = _synthetic(bars=600)
    monkeypatch.setattr(live, "load_bars", lambda symbol, interval, refresh=True: series)
    _stub_study(
        monkeypatch,
        {
            "bars": 5000,
            "horizons": [4, 12],
            "patterns": [
                {
                    "pattern": "inside_bar",
                    "label": "인사이드 바",
                    "direction": "bullish",
                    "horizons": {
                        "4": {"count": 900, "win_rate": 0.58, "base_win_rate": 0.52, "edge_win_rate": 0.06, "average_return": 0.002, "average_mfe": 0.004, "average_mae": -0.003, "t_stat": 3.4, "enough_samples": True},
                        "12": {"count": 900, "win_rate": 0.55, "base_win_rate": 0.54, "edge_win_rate": 0.01, "average_return": 0.001, "average_mfe": 0.006, "average_mae": -0.005, "t_stat": 1.1, "enough_samples": True},
                    },
                }
            ],
        },
    )

    scan = live.scan_live("GC=F", intervals=["1h"], recent_bars=400)
    inside = [signal for signal in scan.signals if signal.pattern == "inside_bar"]
    assert inside, "the stubbed pattern should have been found"
    signal = inside[0]
    assert signal.samples == 900 and signal.win_rate == 0.58
    assert signal.horizon == 4  # the horizon with the strongest record, not the first
    assert signal.confidence == "강함"
    # the projection is the measured excursion applied to the live price
    assert signal.upside_price > signal.last_price > signal.downside_price
    assert any("보장하지 않습니다" in note for note in scan.notes)


def test_a_pattern_that_only_matched_the_market_is_marked_not_a_signal(monkeypatch):
    from goldlab import live

    series = _synthetic(bars=600)
    monkeypatch.setattr(live, "load_bars", lambda symbol, interval, refresh=True: series)
    _stub_study(
        monkeypatch,
        {
            "bars": 5000,
            "horizons": [4],
            "patterns": [
                {
                    "pattern": "inside_bar",
                    "label": "인사이드 바",
                    "direction": "bullish",
                    "horizons": {"4": {"count": 900, "win_rate": 0.52, "base_win_rate": 0.55, "edge_win_rate": -0.03, "average_return": 0.0001, "average_mfe": 0.003, "average_mae": -0.003, "t_stat": 0.4, "enough_samples": True}},
                }
            ],
        },
    )
    scan = live.scan_live("GC=F", intervals=["1h"], recent_bars=400)
    assert all(signal.confidence == "기준 미달" for signal in scan.signals if signal.pattern == "inside_bar")
    assert scan.bias()["direction"] in {"판단 보류", "혼재", "하락 우세"}


def test_a_thin_sample_never_earns_a_verdict(monkeypatch):
    from goldlab import live

    series = _synthetic(bars=600)
    monkeypatch.setattr(live, "load_bars", lambda symbol, interval, refresh=True: series)
    _stub_study(
        monkeypatch,
        {
            "bars": 5000,
            "horizons": [4],
            "patterns": [
                {
                    "pattern": "inside_bar",
                    "label": "인사이드 바",
                    "direction": "bullish",
                    "horizons": {"4": {"count": 8, "win_rate": 0.88, "base_win_rate": 0.52, "edge_win_rate": 0.36, "average_return": 0.02, "average_mfe": 0.03, "average_mae": -0.01, "t_stat": 5.0, "enough_samples": False}},
                }
            ],
        },
    )
    scan = live.scan_live("GC=F", intervals=["1h"], recent_bars=400)
    assert all(signal.confidence == "표본 부족" for signal in scan.signals if signal.pattern == "inside_bar")
    # an eight-sample pattern must not swing the overall read
    assert scan.bias()["counted"] == 0 and scan.bias()["direction"] == "판단 보류"


def test_the_page_states_what_the_numbers_are(monkeypatch):
    from goldlab import live
    from goldlab.report import render_report

    series = _synthetic(bars=600)
    monkeypatch.setattr(live, "load_bars", lambda symbol, interval, refresh=True: series)
    _stub_study(monkeypatch, {"bars": 5000, "horizons": [4], "patterns": []})
    scan = live.scan_live("GC=F", intervals=["1h"], recent_bars=3)

    page = render_report(scan, intervals=["1h"])
    assert "<!doctype html>" in page and "차트 패턴 현황" in page
    assert "예측이 아니라 기록입니다" in page
    assert "종합 판단" in page and "지금 완성된 패턴" in page
    assert page.count("<table") >= 1


def test_sessions_follow_each_market_and_its_daylight_saving():
    from datetime import date as _date
    from goldlab.sessions import SESSION_BY_KEY, session_of, sessions_for

    tokyo_open = datetime(2026, 3, 10, 1, 0, tzinfo=timezone.utc)      # 10:00 Tokyo
    assert session_of(tokyo_open, SESSION_BY_KEY["asia"])
    assert not session_of(tokyo_open, SESSION_BY_KEY["us"])

    # New York's 9am is 14:00 UTC in winter and 13:00 UTC in summer
    assert session_of(datetime(2026, 1, 14, 14, 0, tzinfo=timezone.utc), SESSION_BY_KEY["us"])
    assert session_of(datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc), SESSION_BY_KEY["us"])

    weekend = datetime(2026, 3, 14, 13, 0, tzinfo=timezone.utc)  # Saturday
    assert sessions_for(weekend) == []

    overlap = datetime(2026, 1, 14, 14, 30, tzinfo=timezone.utc)  # London afternoon, NY morning
    assert set(sessions_for(overlap)) >= {"europe", "us"}


def test_session_windows_carry_their_own_high_and_low():
    from goldlab.sessions import SESSION_BY_KEY, session_windows

    stamp = datetime(2026, 1, 14, 13, 0, tzinfo=timezone.utc)  # 8am New York
    rows = []
    for step in range(10):
        price = 2400 + step
        rows.append(_bar(stamp + timedelta(hours=step), price, price + 5, price - 5, price + 1))
    series = bars_from_rows(rows, symbol="GC=F", interval="1h")

    windows = session_windows(series.bars, SESSION_BY_KEY["us"])
    assert len(windows) == 1
    window = windows[0]
    assert window["label"] == "미국"
    inside = series.bars[window["start_index"] : window["end_index"] + 1]
    assert window["high"] == max(bar.high for bar in inside)
    assert window["low"] == min(bar.low for bar in inside)
    assert window["start_index"] > 0  # the 8am bar is before the 8:20 open
    assert window["low"] < window["high"] and window["range"] > 0
    assert window["bars"] == len(inside) >= 5


def test_payrolls_land_on_the_first_friday_at_half_past_eight_in_new_york():
    from zoneinfo import ZoneInfo

    from goldlab.events import first_friday, macro_events

    assert first_friday(2026, 9).weekday() == 4
    rows = macro_events(
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 30, tzinfo=timezone.utc),
        min_stars=3,
        path=None,
    )
    payrolls = [row for row in rows if "고용지표" in row["name"]]
    assert len(payrolls) == 1
    local = datetime.fromisoformat(payrolls[0]["timestamp"]).astimezone(ZoneInfo("America/New_York"))
    assert local.weekday() == 4 and (local.hour, local.minute) == (8, 30)
    assert local.date() == first_friday(2026, 9)


def test_the_chart_marks_patterns_sessions_and_releases(tmp_path):
    from goldlab.chart import build_frame, render_chart

    series = _synthetic(bars=400)
    frame = build_frame(series, study=None, max_bars=300, min_stars=2)
    assert len(frame["bars"]) == 300
    assert frame["hits"] and all("index" in hit and "confidence" in hit for hit in frame["hits"])
    assert frame["sessions"] and {row["session"] for row in frame["sessions"]} <= {"asia", "europe", "us"}
    assert all(window["high"] >= window["low"] for window in frame["sessions"])

    page = render_chart({"1h": frame}, symbol="GC=F")
    assert "<canvas id=\"chart\"" in page
    assert "noindex" in page  # a private chart, even when served
    assert "세션 고저" in page and "경제지표" in page and "완성 패턴" in page and "형성 중인 패턴" in page
    for label in ("아시아", "유럽", "미국"):
        assert label in page


def test_a_pattern_without_a_measurement_is_marked_as_such():
    from goldlab.chart import _hit_rows
    from goldlab.patterns import detect_patterns

    series = _synthetic(bars=400)
    hits = detect_patterns(series)[:5]
    rows = _hit_rows(hits, None)
    assert rows and all(row["confidence"] == "측정 없음" and row["samples"] == 0 for row in rows)

    study = {
        "patterns": [
            {"pattern": hits[0].pattern, "horizons": {"4": {"count": 500, "win_rate": 0.6, "edge_win_rate": 0.07, "t_stat": 3.5}}}
        ]
    }
    measured = _hit_rows(hits, study)
    assert measured[0]["confidence"] == "강함" and measured[0]["samples"] == 500


def test_the_cache_falls_back_when_the_home_directory_cannot_be_written(tmp_path, monkeypatch):
    """A serverless host mounts home read-only; the chart still has to render."""

    import pathlib

    import goldlab.data as data
    from goldlab.events import macro_events, events_file

    monkeypatch.delenv("GOLDLAB_CACHE_DIR", raising=False)
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: pathlib.Path("/read-only-home")))

    real_mkdir = pathlib.Path.mkdir

    def refuse_outside_tmp(self, *args, **kwargs):
        if str(self).replace("\\", "/").startswith("/read-only-home"):
            raise OSError(30, "Read-only file system")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "mkdir", refuse_outside_tmp)
    monkeypatch.setattr(data.tempfile, "gettempdir", lambda: str(tmp_path))

    assert data.cache_dir() == tmp_path / "goldlab" / "bars"
    assert data.cache_dir().exists()
    assert events_file() == tmp_path / "goldlab" / "events.csv"

    # The releases that follow a rule still appear; the operator's file is absent.
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    events = macro_events(start, start + timedelta(days=20), min_stars=3)
    assert events and all(row["source"] == "rule" for row in events)


def test_moving_averages_and_trend_lines_come_from_the_bars():
    from goldlab.indicators import exponential_moving_average, simple_moving_average, trend_lines

    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert simple_moving_average(values, 3) == [None, None, 2.0, 3.0, 4.0]
    ema = exponential_moving_average(values, 3)
    assert ema[:2] == [None, None] and ema[2] == 2.0 and ema[3] > 2.0
    with pytest.raises(ValueError):
        simple_moving_average(values, 0)

    series = _synthetic(bars=500)
    lines = trend_lines(series.bars)
    assert {line["kind"] for line in lines} <= {"low", "high"}
    for line in lines:
        assert line["to_index"] == len(series.bars) - 1
        assert line["from_index"] < line["anchor_index"] <= line["to_index"]
        assert line["label"] in {"지지선", "저항선"} and isinstance(line["broken"], bool)


def _double_bottom_bars(*, broken: bool):
    """A fall, a bounce to a neckline, a second matching low, then the bar after."""

    stamp = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = []

    def add(open_, high, low, close):
        nonlocal stamp
        stamp += timedelta(hours=1)
        rows.append(_bar(stamp, open_, high, low, close))

    price = 4000.0
    for _ in range(30):                       # a quiet run-in so pivots exist
        add(price, price + 2, price - 2, price)
    for _ in range(8):                        # down to the first low
        add(price, price + 1, price - 12, price - 10)
        price -= 10
    first_low = price
    for _ in range(8):                        # up to the neckline
        add(price, price + 12, price - 1, price + 10)
        price += 10
    neckline = price
    for _ in range(8):                        # down to a matching second low
        add(price, price + 1, price - 12, price - 10)
        price -= 10
    assert abs(price - first_low) < 1
    for _ in range(5):                        # a partial bounce, short of the neckline
        add(price, price + 8, price - 1, price + 6)
        price += 6
    if broken:
        add(price, neckline + 15, price - 1, neckline + 12)
    else:
        add(price, price + 2, price - 2, price)
    return bars_from_rows(rows, symbol="GC=F", interval="1h"), neckline


def test_a_double_bottom_is_reported_while_it_forms_and_not_after_it_breaks():
    from goldlab.patterns.forming import attach_record, detect_forming

    series, neckline = _double_bottom_bars(broken=False)
    forming = detect_forming(series.bars)
    bottoms = [row for row in forming if row["pattern"] == "double_bottom"]
    assert bottoms, [row["pattern"] for row in forming]
    shape = bottoms[0]
    assert shape["direction"] == "bullish"
    assert abs(shape["trigger"] - neckline) < 15          # the neckline is the bounce's high
    assert shape["distance"] > 0                          # and it sits above the last close
    assert "넥라인" in shape["trigger_label"]

    study = {"patterns": [{"pattern": "double_bottom", "horizons": {"12": {"count": 80, "win_rate": 0.61, "edge_win_rate": 0.09, "t_stat": 2.4}}}]}
    quoted = attach_record(bottoms, study)[0]
    assert quoted["samples"] == 80 and quoted["confidence"] == "보통" and quoted["win_rate"] == 0.61
    assert attach_record(bottoms, None)[0]["confidence"] == "측정 없음"

    broken, _ = _double_bottom_bars(broken=True)
    assert not [row for row in detect_forming(broken.bars) if row["pattern"] == "double_bottom"]


def test_the_frame_reads_korean_time_and_carries_lines_forecasts_and_a_bias():
    from goldlab.chart import build_frame, render_chart, summarise_bias

    series = _synthetic(bars=400)
    frame = build_frame(series, study=None, max_bars=300)
    first_utc = series.bars[-300].timestamp
    assert frame["bars"][0][0] == first_utc.astimezone(ZoneInfo("Asia/Seoul")).strftime("%m-%d %H:%M")
    assert set(frame["ma"]) == {"20", "50", "200"} and len(frame["ma"]["20"]) == 300
    assert frame["ma"]["200"][198] is None and frame["ma"]["200"][199] is not None
    assert isinstance(frame["trendlines"], list) and isinstance(frame["forming"], list)
    assert frame["bias"]["direction"] == "판단 보류"      # nothing measured, so nothing to weigh
    assert frame["generated_label"].count(":") == 2

    daily_rows = []
    for month in (9, 10, 11):
        for day in range(1, 29):
            daily_rows.append(_bar(datetime(2026, month, day, 4, tzinfo=timezone.utc), 4000, 4010, 3990, 4005))
    daily = bars_from_rows(daily_rows, symbol="GC=F", interval="1d")
    daily_frame = build_frame(daily, study=None, max_bars=100)
    assert daily_frame["bars"][-1][0] == "2026-11-28"     # a daily bar shows its date, not a clock

    strong_up = [{"direction": "bullish", "samples": 100, "edge_win_rate": 0.12, "t_stat": 3.0}]
    weak_down = [{"direction": "bearish", "samples": 100, "edge_win_rate": 0.02, "t_stat": 1.0}]
    assert summarise_bias(strong_up, weak_down)["direction"] == "상승 우세"
    assert summarise_bias([], [])["direction"] == "판단 보류"
    assert summarise_bias([{"direction": "bullish", "samples": 5, "edge_win_rate": 0.5, "t_stat": 5}], [])["direction"] == "판단 보류"

    live = render_chart({"1h": frame}, symbol="GC=F", intervals=("1m", "1h", "1d"), data_url="/lab/gold/data", bars=300)
    assert '"data_url": "/lab/gold/data"' in live and 'data-interval="1m"' in live and 'data-interval="1d"' in live
    assert "시세로 움직이고" in live and "quote_seconds" in live and "이동평균" in live and "추세선" in live and "KST" in live
    static = render_chart({"1h": frame}, symbol="GC=F")
    assert '"data_url": null' in static and "정지 화면" in static


def test_the_served_chart_fetches_one_timeframe_at_a_time(monkeypatch):
    from fastapi.testclient import TestClient

    import goldlab.data as data
    from tradingagents.site import create_app

    calls: list[str] = []

    def fake_fetch(symbol="GC=F", *, interval="1h", days=None):
        calls.append(interval)
        if interval == "1mo":
            raise RuntimeError("vendor has nothing")
        return _synthetic(bars=400)

    monkeypatch.setattr(data, "fetch_bars", fake_fetch)
    app = create_app(repo=None, load_repo_from_env=False, trust_member_user_header=False)
    client = TestClient(app)

    page = client.get("/lab/gold?bars=200")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "private, no-store"
    assert calls == ["1h"]                                 # only the opening timeframe is fetched up front
    assert 'data-interval="1mo"' in page.text and "형성 중인 패턴" in page.text

    fresh = client.get("/lab/gold/data?interval=15m&bars=200")
    assert fresh.status_code == 200 and fresh.headers["cache-control"] == "private, no-store"
    body = fresh.json()
    assert len(body["bars"]) == 200 and "forming" in body and "ma" in body and "bias" in body

    assert client.get("/lab/gold/data?interval=7h").status_code == 400
    assert client.get("/lab/gold/data?interval=1mo").status_code == 503

    quote = client.get("/lab/gold/quote?interval=5m")
    assert quote.status_code == 200 and quote.headers["cache-control"] == "private, no-store"
    body = quote.json()
    assert len(body["bars"]) == 3 and body["bucket_seconds"] == 3600 and len(body["bars"][-1]) == 6   # the synthetic series is hourly whatever was asked
    assert body["bars"][-1][5] == int(_synthetic(bars=400).bars[-1].timestamp.timestamp())
    assert client.get("/lab/gold/quote?interval=9h").status_code == 400
    assert client.get("/lab/gold/quote?interval=1mo").status_code == 503


def test_every_bar_carries_the_second_that_tells_candles_apart():
    from goldlab.chart import build_frame, quote_payload

    series = _synthetic(bars=200)
    frame = build_frame(series, study=None, max_bars=100)
    assert frame["bucket_seconds"] == 3600
    assert all(len(row) == 6 and isinstance(row[5], int) for row in frame["bars"])
    assert frame["bars"][-1][5] == int(series.bars[-1].timestamp.timestamp())
    quote = quote_payload(series, last=2)
    assert [row[5] for row in quote["bars"]] == [int(bar.timestamp.timestamp()) for bar in series.bars[-2:]]
    assert quote["last_price"] == series.bars[-1].close
    assert quote["delay_seconds"] > 3600          # the synthetic bars are dated 2025, so far behind
    assert frame["delay_seconds"] == quote["delay_seconds"] or abs(frame["delay_seconds"] - quote["delay_seconds"]) < 5
