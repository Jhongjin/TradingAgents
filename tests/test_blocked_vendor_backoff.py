"""A vendor that is blocked stays blocked for the run, and is only asked once.

pykrx reads index data from data.krx.co.kr. Where that host is unreachable it
is unreachable for the whole run, but every caller was trying it first anyway:
a daily shorts build made 241 attempts at 175ms each — 42 seconds of waiting,
and 241 error lines that buried everything else in the log.
"""

import pytest

from tradingagents.dataflows import kr_returns


@pytest.fixture(autouse=True)
def _fresh_flag(monkeypatch):
    monkeypatch.setattr(kr_returns, "_index_vendor_down", False)


def _counting_module(behaviour):
    calls = {"n": 0}

    class _Stock:
        @staticmethod
        def get_index_ohlcv_by_date(start, end, code):
            calls["n"] += 1
            return behaviour()

    _Stock.calls = calls
    return _Stock


def test_a_blocked_index_endpoint_is_asked_once_and_then_left_alone(monkeypatch):
    def blocked():
        raise RuntimeError("data.krx.co.kr refused the connection")

    module = _counting_module(blocked)
    monkeypatch.setattr(kr_returns, "_get_pykrx_stock_module", lambda: module)
    monkeypatch.setattr(kr_returns, "_yfinance_benchmark_close",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no yahoo either")))

    for _ in range(20):
        assert kr_returns.fetch_benchmark_close(on_date="2026-09-18") is None

    assert module.calls["n"] == 1
    assert kr_returns._index_vendor_down is True


def test_an_empty_answer_counts_as_blocked_too(monkeypatch):
    """A 200 with no rows is the other way that host fails here."""

    import pandas as pd

    module = _counting_module(lambda: pd.DataFrame())
    monkeypatch.setattr(kr_returns, "_get_pykrx_stock_module", lambda: module)
    monkeypatch.setattr(kr_returns, "_yfinance_benchmark_close",
                        lambda *a, **k: pd.Series(dtype=float))

    for _ in range(5):
        kr_returns.fetch_benchmark_close(on_date="2026-09-18")
    assert module.calls["n"] == 1


def test_a_vendor_that_works_is_not_written_off(monkeypatch):
    import pandas as pd

    frame = pd.DataFrame({"종가": [2_400.0, 2_450.0]},
                         index=pd.to_datetime(["2026-09-17", "2026-09-18"]))
    module = _counting_module(lambda: frame)
    monkeypatch.setattr(kr_returns, "_get_pykrx_stock_module", lambda: module)

    for _ in range(3):
        assert kr_returns.fetch_benchmark_close(on_date="2026-09-18") == 2_450.0
    assert module.calls["n"] == 3          # still asked every time
    assert kr_returns._index_vendor_down is False


def test_the_flag_does_not_leak_between_runs():
    """Per-process on purpose: a network blocked now may not be tomorrow."""

    import inspect

    source = inspect.getsource(kr_returns)
    assert "_index_vendor_down = False" in source
    # and it is a module global, not persisted anywhere
    assert "_index_vendor_down" not in kr_returns.__dict__.get("__file__", "")


def test_the_whole_market_loader_stops_after_one_refusal(monkeypatch):
    """48 calls at 1.1s each, every one certain to fail, before it gave up."""

    from tradingagents.dataflows.errors import VendorUnavailableError
    from tradingagents.screener import universe

    monkeypatch.setattr(universe, "_whole_market_down", False)
    calls = {"n": 0}

    def blocked(compact, market):
        calls["n"] += 1
        raise RuntimeError("data.krx.co.kr refused the connection")

    with pytest.raises(VendorUnavailableError):
        universe.load_market_snapshot(
            "2026-09-18",
            ohlcv_fetcher=blocked, cap_fetcher=blocked, fundamental_fetcher=blocked,
            name_lookup=lambda code: code,
        )

    assert calls["n"] == 1


def test_a_whole_market_vendor_that_answers_is_not_written_off(monkeypatch):
    import pandas as pd

    from tradingagents.screener import universe

    monkeypatch.setattr(universe, "_whole_market_down", False)
    calls = {"n": 0}

    def working(compact, market):
        calls["n"] += 1
        return pd.DataFrame(
            {"종가": [70_000.0], "거래량": [1_000_000.0], "거래대금": [7e10], "등락률": [1.2]},
            index=["005930"],
        )

    snapshot = universe.load_market_snapshot(
        "2026-09-18",
        ohlcv_fetcher=working, cap_fetcher=working, fundamental_fetcher=working,
        name_lookup=lambda code: "삼성전자",
    )
    assert snapshot.rows
    assert calls["n"] > 1
    assert universe._whole_market_down is False


def test_the_cli_bounds_how_long_a_screen_may_take():
    """An unattended morning run had nothing stopping it; the web path always did."""

    import inspect

    import cli.main as main

    assert main._screen_time_budget_seconds() > 0
    source = inspect.getsource(main.pipeline_command)
    assert "time_budget_seconds=_screen_time_budget_seconds()" in source
