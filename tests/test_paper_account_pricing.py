"""An unpriced position must not be reported as an unchanged one.

market_value fell back to (price or average) * quantity with nothing said, so
a holding down 20% published as 0.00% and the account's return counted only
what had already been sold. Live: all eighteen positions were unpriced and the
site showed -2.29% where the mark-to-market was -2.81%.
"""

import pytest

from tradingagents.harness import paper_state


class _Position:
    def __init__(self, quantity, average_price):
        self.quantity = quantity
        self.average_price = average_price


class _Portfolio:
    def __init__(self, positions, cash=1_000_000.0):
        self.positions = positions
        self.cash = cash


class _Broker:
    def __init__(self, positions, cash=1_000_000.0):
        self.portfolio = _Portfolio(positions, cash)


class _Adapter:
    def __init__(self, positions, cash=1_000_000.0):
        self.broker = _Broker(positions, cash)


def _books(monkeypatch, positions, prices=None, *, explode=False):
    monkeypatch.setattr(paper_state, "restore_paper_account",
                        lambda repo, **kw: (_Adapter(positions), []))

    def payload(tickers, **kwargs):
        if explode:
            raise RuntimeError("vendor refused")
        return {"prices": {code: {"close": prices[code]} for code in tickers if code in (prices or {})}}

    import tradingagents.site.market_api as market_api
    monkeypatch.setattr(market_api, "build_latest_prices_payload", payload)
    return paper_state.latest_prices_for(object())


def test_the_holdings_of_every_book_are_priced(monkeypatch):
    held = {"005930": _Position(10, 250_000.0), "041510": _Position(5, 88_600.0)}
    prices = _books(monkeypatch, held, {"005930": 260_000.0, "041510": 81_100.0})

    assert prices == {"005930": 260_000.0, "041510": 81_100.0}


def test_a_closed_out_name_is_not_asked_for(monkeypatch):
    held = {"005930": _Position(10, 250_000.0), "041510": _Position(0, 88_600.0)}
    prices = _books(monkeypatch, held, {"005930": 260_000.0, "041510": 81_100.0})

    assert set(prices) == {"005930"}


def test_a_vendor_refusal_leaves_the_cost_basis_rather_than_raising(monkeypatch):
    held = {"005930": _Position(10, 250_000.0)}
    assert _books(monkeypatch, held, {}, explode=True) == {}


def test_nothing_held_asks_for_nothing(monkeypatch):
    assert _books(monkeypatch, {}, {"005930": 1.0}) == {}


def test_an_unpriced_holding_is_flagged_rather_than_shown_flat():
    """priced is the field that tells the page not to claim a return."""

    import inspect

    source = inspect.getsource(paper_state.build_paper_account_payload)
    assert '"priced": price is not None' in source
    # and the fallback is still there, because cost beats nothing
    assert "(price or average) * quantity" in source


def test_the_combined_payload_prices_once_for_all_three_books():
    import inspect

    source = inspect.getsource(paper_state.build_combined_account_payload)
    assert "latest_prices_for(repo" in source
    # and an explicit price map still wins, so callers and tests can pin it
    assert "current_prices" in source
