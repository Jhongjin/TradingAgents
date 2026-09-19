"""Intraday prices for the exits pass, and what happens when NH is not there.

The chart vendors return the last daily bar. An exits pass run during the
session against that compares this morning's cost with yesterday's close and
finds nothing, which is how a 5% stop came to realise 8.81% on average.
"""

import cli.main as main


class _NH:
    def __init__(self, prices=None, fail=()):
        self.prices = prices or {}
        self.fail = set(fail)
        self.asked = []

    def current_price(self, code, *, market="KRX"):
        self.asked.append(code)
        if code in self.fail:
            raise RuntimeError(f"vendor said no to {code}")
        return {"rsp_cd": "00000", "Output_0": {"stck_prpr": self.prices.get(code, 0)}}


def _patch(monkeypatch, client, *, configured=True):
    import tradingagents.execution.nh_client as nh

    class _Config:
        configured = True

    monkeypatch.setattr(nh.NHConfig, "from_env",
                        classmethod(lambda cls, **kw: type("C", (), {"configured": configured})()))
    monkeypatch.setattr(nh, "NHClient", lambda **kwargs: client)
    return client


def test_held_positions_are_priced_from_nh(monkeypatch):
    client = _patch(monkeypatch, _NH({"005930": 260_000, "041510": 81_600}))

    prices, source = main._live_prices(["005930", "041510"])

    assert prices == {"005930": 260_000.0, "041510": 81_600.0}
    assert source == {"NH": 2}


def test_one_ticker_failing_does_not_lose_the_others(monkeypatch):
    client = _patch(monkeypatch, _NH({"005930": 260_000}, fail={"041510"}))

    prices, source = main._live_prices(["005930", "041510"])

    assert prices == {"005930": 260_000.0}
    assert source == {"NH": 1}
    assert client.asked == ["005930", "041510"]        # it kept going


def test_a_zero_price_is_not_a_price(monkeypatch):
    """A halted or unquoted name answers 0, and a 0 stop-check sells everything."""

    _patch(monkeypatch, _NH({"005930": 0}))
    prices, source = main._live_prices(["005930"])
    assert prices == {} and source == {}


def test_without_nh_configured_nothing_is_asked_and_nothing_breaks(monkeypatch):
    client = _patch(monkeypatch, _NH({"005930": 260_000}), configured=False)

    prices, source = main._live_prices(["005930"])

    assert prices == {} and source == {}
    assert client.asked == []


def test_no_holdings_is_no_call_at_all(monkeypatch):
    client = _patch(monkeypatch, _NH())
    assert main._live_prices([]) == ({}, {})
    assert client.asked == []


def test_the_intraday_task_runs_both_books_and_only_closes():
    """A comparison between two accounts is meaningless if the rule differs."""

    from pathlib import Path

    script = Path("automation/intraday-exits.cmd").read_text(encoding="utf-8")
    assert "--exits-only" in script
    assert "for %%A in (paper rules)" in script
    # an exits pass must never open anything, and must never reach an LLM
    assert "--confirmer none" in script
    assert "--broker paper" in script
    assert "--confirmer playbook" not in script and "--confirmer debate" not in script
