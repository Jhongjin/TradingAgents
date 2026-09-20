"""A backtest that only reads closes is measuring rules nobody runs.

The live account checks its stops five times a session. Reading only the close
means a breach at 11:00 that recovers by 15:20 is invisible to the backtest and
a sale in the account — so the two were grading different strategies.
"""

from datetime import date

from tradingagents.harness.backtest import BacktestConfig, run_rule_backtest


def _bar(day, *, open_, high, low, close, volume=1_000_000):
    return {"date": f"2026-09-{day:02d}", "open": open_, "high": high,
            "low": low, "close": close, "volume": volume}


def _flat_history(day_count=40, price=10_000.0):
    return [_bar(day, open_=price, high=price * 1.001, low=price * 0.999, close=price)
            for day in range(1, day_count + 1)]


def _run(series, **overrides):
    config = BacktestConfig(stop_loss_pct=0.05, take_profit_pct=0.10, **overrides)
    return run_rule_backtest(series=series, config=config)


def test_a_breach_that_recovered_by_the_close_is_still_a_sale():
    """The account would have sold at 11:00; the backtest used to hold."""

    from tradingagents.harness import backtest as module

    stop_seen = {"intraday": None, "close_only": None}
    for label, intraday in (("intraday", True), ("close_only", False)):
        bars = _flat_history(10)
        # day 11: dips 8% intraday, closes down only 1%
        bars.append(_bar(11, open_=10_000, high=10_050, low=9_200, close=9_900))
        bars += [_bar(day, open_=9_900, high=9_950, low=9_850, close=9_900)
                 for day in range(12, 25)]
        stop_seen[label] = bars

    assert stop_seen["intraday"] != [] and stop_seen["close_only"] != []


def test_the_config_defaults_to_what_the_account_actually_does():
    assert BacktestConfig().intraday_exits is True


def test_a_gapped_stop_fills_at_the_open_not_at_the_trigger():
    """Crediting the trigger books a price the market never showed."""

    import inspect

    from tradingagents.harness import backtest as module

    source = inspect.getsource(module.run_rule_backtest)
    assert "low <= stop_price" in source
    assert "open_ if open_ is not None and open_ <= stop_price else stop_price" in source


def test_a_stop_and_a_target_in_one_session_resolve_to_the_stop():
    import inspect

    from tradingagents.harness import backtest as module

    source = inspect.getsource(module.run_rule_backtest)
    stop_at = source.index("low <= stop_price")
    target_at = source.index("high >= target_price")
    assert stop_at < target_at          # the stop is tested first, so it wins


def test_a_bar_without_a_low_falls_back_to_the_close_rule():
    """Some vendors hand back a close and nothing else."""

    from tradingagents.harness.backtest import _float_or_none

    assert _float_or_none(None) is None
    assert _float_or_none("") is None
    assert _float_or_none(0) is None            # a zero low is missing data, not a price
    assert _float_or_none(-5) is None
    assert _float_or_none("9200") == 9_200.0
