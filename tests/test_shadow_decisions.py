"""A record that cannot trade.

A file of directional calls with prices beside them is exactly what somebody
skims later and mistakes for a track record, so every row says outright that
no order was placed — and no code path here can place one.
"""

import json
from datetime import datetime, timezone

import pytest

from tradingagents.decisions import shadow
from tradingagents.decisions.typed import Choice


class _Bar:
    def __init__(self, day, close):
        self.timestamp = datetime(2026, 9, 1, tzinfo=timezone.utc).replace(day=min(day, 28))
        self.close = close


def _bars(count=60, start=100.0, step=1.0):
    return [_Bar(min(i + 1, 28), start + i * step) for i in range(count)]


def _choice(pick="buy", probabilities=None):
    return Choice(name="direction", choice=pick,
                  probabilities=probabilities or {"buy": 0.7, "wait": 0.2, "avoid": 0.1},
                  confidence=0.66)


def test_the_package_places_no_orders():
    """The guarantee the whole thing rests on, checked rather than asserted in prose."""

    import inspect

    from tradingagents.decisions import shadow as s
    from tradingagents.decisions import typed as t

    for module in (s, t):
        source = inspect.getsource(module)
        for forbidden in ("place_order", "submit_order", "OrderIntent", "cashBuy", "cashSell"):
            assert forbidden not in source, f"{module.__name__} mentions {forbidden}"


def test_every_row_says_it_was_not_traded(tmp_path):
    path = tmp_path / "shadow.jsonl"
    state = {"as_of": "2026-09-20", "latest_close": 195_310.0}
    row = shadow.make_record(instrument="KRXGOLD", state=state,
                             answers={"direction": _choice()}, model="jev-1.13.0")

    assert shadow.record([row], path=path) == 1
    stored = json.loads(path.read_text(encoding="utf-8").strip())
    assert stored["traded"] is False
    assert "주문은 없었습니다" in stored["note"]
    assert stored["answers"]["direction"]["probabilities"]["buy"] == 0.7


def test_the_state_carries_prices_and_nothing_derived():
    state = shadow.build_state(_bars(), label="KRX 금현물", unit="원/g")

    assert state["as_of"] and state["latest_close"] == 159.0
    assert len(state["closes"]) == 60
    # no indicator that would weigh the evidence for it
    for leaked in ("rsi", "macd", "signal", "score", "recommendation"):
        assert leaked not in json.dumps(state).lower()


def test_too_short_a_history_is_refused_rather_than_asked_about():
    with pytest.raises(ValueError, match="too few"):
        shadow.build_state(_bars(10), label="x", unit="y")


def test_asking_twice_in_a_day_is_detectable(tmp_path):
    """Keeping both answers would let a re-run quietly pick the one it liked."""

    path = tmp_path / "shadow.jsonl"
    state = {"as_of": "2026-09-20", "latest_close": 1.0}
    shadow.record([shadow.make_record(instrument="BTC", state=state,
                                      answers={"direction": _choice()}, model="m")], path=path)

    assert shadow.already_recorded("2026-09-20", "BTC", path=path) is True
    assert shadow.already_recorded("2026-09-20", "KRXGOLD", path=path) is False
    assert shadow.already_recorded("2026-09-21", "BTC", path=path) is False


def test_a_missing_log_is_empty_rather_than_an_error(tmp_path):
    assert shadow.read_log(path=tmp_path / "absent.jsonl") == []
    assert shadow.already_recorded("2026-09-20", "BTC", path=tmp_path / "absent.jsonl") is False


def test_a_corrupt_line_does_not_lose_the_rest(tmp_path):
    path = tmp_path / "shadow.jsonl"
    path.write_text('{"as_of": "2026-09-19"}\nnot json\n{"as_of": "2026-09-20"}\n', encoding="utf-8")
    assert [row["as_of"] for row in shadow.read_log(path=path)] == ["2026-09-19", "2026-09-20"]


def test_shorting_is_not_one_of_the_options():
    """The accounts behind this are long-only; naming a short invites reading
    a record of trades nobody could have made."""

    keys = {key for key, _ in shadow.DIRECTION_OPTIONS}
    assert keys == {"buy", "wait", "avoid"}
    assert "short" not in json.dumps(shadow.DIRECTION_OPTIONS, ensure_ascii=False).lower()


def test_an_unknown_instrument_is_refused():
    with pytest.raises(ValueError, match="unknown instrument"):
        shadow.decide(object(), _bars(), instrument="TSLA")


def test_the_instruments_are_ones_already_priced_by_existing_code():
    from goldlab.data import KRX_GOLD_SYMBOLS

    assert shadow.INSTRUMENTS["KRXGOLD"]["symbol"] in KRX_GOLD_SYMBOLS
    assert shadow.INSTRUMENTS["BTC"]["symbol"] == "BTC-USD"
    assert shadow.INSTRUMENTS["COMEXGOLD"]["symbol"] == "GC=F"


def test_the_cli_command_cannot_reach_an_order_path():
    """The command is the only entry point; it must stay unable to trade."""

    import inspect

    import cli.main as main

    source = inspect.getsource(main.shadow_decide_command)
    for forbidden in ("place_order", "submit_order", "--execute", "OrderIntent", "broker"):
        assert forbidden not in source, f"shadow-decide mentions {forbidden}"
    assert "never trades" in source


def test_the_command_refuses_without_a_key(monkeypatch):
    import typer
    from typer.testing import CliRunner

    import cli.main as main

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = CliRunner().invoke(main.app, ["shadow-decide"])

    assert result.exit_code == 2
    assert "TYPESAFE_API_KEY" in result.output


def test_an_unknown_instrument_is_refused_by_the_command(monkeypatch):
    from typer.testing import CliRunner

    import cli.main as main

    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    result = CliRunner().invoke(main.app, ["shadow-decide", "--instruments", "TSLA"])
    assert result.exit_code != 0
