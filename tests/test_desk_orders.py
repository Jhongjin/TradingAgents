"""What the desk refuses before the broker is asked, and what it writes after."""

import json

import pytest
from fastapi.testclient import TestClient

from tradingagents.desk import create_desk_app
from tradingagents.desk.orders import (
    Limits,
    OrderRefused,
    check,
    new_attempt,
    record,
    today_spent,
)
from tradingagents.execution.audit import AuditLedger

OK = dict(side="buy", code="005930", quantity=2, price=100_000,
          confirmation="2", mode="paper", limits=Limits(),
          spent_today=0, orders_today=0)


def test_the_quantity_has_to_be_typed_twice():
    """A button that needs one click is a button that gets clicked by accident."""

    assert check(**OK) == 200_000
    with pytest.raises(OrderRefused, match="확인란에 수량 2"):
        check(**{**OK, "confirmation": ""})
    with pytest.raises(OrderRefused, match="확인란에 수량 2"):
        check(**{**OK, "confirmation": "3"})
    # the same number with spaces around it is still the same number
    assert check(**{**OK, "confirmation": " 2 "}) == 200_000


def test_one_order_cannot_exceed_the_single_order_cap():
    with pytest.raises(OrderRefused, match="1회 한도"):
        check(**{**OK, "quantity": 20, "confirmation": "20"})


def test_the_day_has_a_cap_in_won_and_in_count():
    with pytest.raises(OrderRefused, match="일일 한도"):
        check(**{**OK, "spent_today": 2_900_000})
    with pytest.raises(OrderRefused, match="주문 10건"):
        check(**{**OK, "orders_today": 10})


def test_nonsense_is_refused_before_anything_is_sent():
    for bad in ({"side": "short"}, {"quantity": 0, "confirmation": "0"},
                {"price": 0}, {"mode": "unknown"}):
        with pytest.raises(OrderRefused):
            check(**{**OK, **bad})


def test_a_refused_order_does_not_eat_the_daily_cap(tmp_path):
    """The market being shut is not a trade; 14580 must not lock out the open day."""

    book = AuditLedger(tmp_path / "orders.jsonl")
    common = dict(side="buy", code="005930", quantity=1, price=100_000,
                  amount=100_000, mode="paper")

    failed = new_attempt()
    record(book, stage="sent", attempt=failed, **common)
    record(book, stage="failed", attempt=failed, error="14580", **common)
    assert today_spent(book) == (0, 0)

    landed = new_attempt()
    record(book, stage="sent", attempt=landed, **common)
    record(book, stage="accepted", attempt=landed, result={"rsp_cd": "00047"}, **common)
    assert today_spent(book) == (100_000, 1)


def test_an_attempt_with_no_ending_counts_against_the_cap(tmp_path):
    """If it is not known whether the order landed, assume it did."""

    book = AuditLedger(tmp_path / "orders.jsonl")
    record(book, stage="sent", attempt=new_attempt(), side="buy", code="005930",
           quantity=1, price=100_000, amount=100_000, mode="paper")
    assert today_spent(book) == (100_000, 1)


def test_yesterdays_orders_do_not_count_against_today(tmp_path):
    book = AuditLedger(tmp_path / "orders.jsonl")
    book.append("desk.order", {"stage": "sent", "attempt": "a", "date": "2000-01-01",
                               "amount": 500_000, "mode": "paper"})
    assert today_spent(book) == (0, 0)


def test_limits_come_from_the_environment_and_ignore_nonsense(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_DESK_MAX_ORDER_KRW", "250000")
    monkeypatch.setenv("TRADINGAGENTS_DESK_MAX_DAILY_KRW", "0")        # not a limit
    monkeypatch.setenv("TRADINGAGENTS_DESK_MAX_DAILY_ORDERS", "abc")   # not a number
    rules = Limits.from_env()
    assert rules.max_order_krw == 250_000
    assert rules.max_daily_krw == 3_000_000 and rules.max_daily_orders == 10


class _Broker:
    def __init__(self, *, fail=None):
        self.fail, self.sent = fail, []

    def balance(self, account_no=None):
        return {"rsp_cd": "00000", "Output_0": {}, "Output_1": []}

    def place_order(self, **kwargs):
        self.sent.append(kwargs)
        if self.fail:
            raise RuntimeError(self.fail)
        return {"rsp_cd": "00047", "rsp_msg": "매수 주문이 완료되었습니다.",
                "Output_0": {"mkt_orr_no": 12345}}


def _desk(broker, tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_AUDIT_LOG_PATH", str(tmp_path / "orders.jsonl"))
    monkeypatch.setenv("NH_IS_PAPER", "true")
    app = create_desk_app(token="T", client_factory=lambda: broker)
    return TestClient(app, base_url="http://127.0.0.1:8787")


def _body(**overrides):
    return {"side": "buy", "code": "005930", "quantity": 1, "price": 100_000,
            "confirmation": "1", **overrides}


def test_an_accepted_order_is_written_before_and_after_the_broker_call(tmp_path, monkeypatch):
    """A crash mid-flight must still leave a record that it was attempted."""

    broker = _Broker()
    with _desk(broker, tmp_path, monkeypatch) as http:
        result = http.post("/api/order?t=T", json=_body()).json()

    assert result["ok"] is True and result["order_no"] == 12345
    assert broker.sent == [{"side": "buy", "code": "005930", "quantity": 1, "price": 100_000}]

    lines = [json.loads(line) for line in (tmp_path / "orders.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [line["payload"]["stage"] for line in lines] == ["sent", "accepted"]
    # both lines belong to one attempt, which is how the cap tells them apart
    assert len({line["payload"]["attempt"] for line in lines}) == 1
    # and the chain is intact, so a line cannot be removed unnoticed
    assert all(line["hash"] for line in lines)


def test_a_broker_refusal_is_recorded_with_its_reason(tmp_path, monkeypatch):
    broker = _Broker(fail="14580: 장운영일이 아닙니다.")
    with _desk(broker, tmp_path, monkeypatch) as http:
        response = http.post("/api/order?t=T", json=_body())
    assert response.status_code == 502 and "14580" in response.json()["error"]

    lines = [json.loads(line) for line in (tmp_path / "orders.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [line["payload"]["stage"] for line in lines] == ["sent", "failed"]
    assert "14580" in lines[-1]["payload"]["error"]


def test_a_refused_order_never_reaches_the_broker(tmp_path, monkeypatch):
    broker = _Broker()
    with _desk(broker, tmp_path, monkeypatch) as http:
        response = http.post("/api/order?t=T", json=_body(confirmation=""))
    assert response.status_code == 400
    assert broker.sent == []
    assert not (tmp_path / "orders.jsonl").exists()      # nothing happened to record


def test_the_order_route_is_behind_the_same_guard(tmp_path, monkeypatch):
    broker = _Broker()
    with _desk(broker, tmp_path, monkeypatch) as http:
        assert http.post("/api/order", json=_body()).status_code == 401
        blocked = http.post("/api/order?t=T", json=_body(), headers={"sec-fetch-site": "cross-site"})
        assert blocked.status_code == 403
    assert broker.sent == []


def test_the_desk_says_what_is_left_of_today(tmp_path, monkeypatch):
    broker = _Broker()
    with _desk(broker, tmp_path, monkeypatch) as http:
        http.post("/api/order?t=T", json=_body())
        limits = http.get("/api/limits?t=T").json()
    assert limits["spent_today"] == 100_000 and limits["orders_today"] == 1
    assert limits["mode"] == "paper"


def test_only_cash_buy_and_sell_are_wired():
    """Credit and reserved orders are a different risk conversation."""

    from tradingagents.execution.nh_client import ORDER_PATHS

    assert set(ORDER_PATHS) == {"buy", "sell"}
    assert ORDER_PATHS["buy"] == ("/krstock/order/v1/cashBuy", "SCSOS61803A")
    assert ORDER_PATHS["sell"] == ("/krstock/order/v1/cashSell", "SCSOS61801A")


def test_there_is_no_market_order_because_the_code_is_undocumented():
    """Guessing which value means at market sells at any price it can find."""

    import inspect

    from tradingagents.execution.nh_client import NHClient

    source = inspect.getsource(NHClient.place_order)
    assert '"nmn_pr_tp_cd": "01"' in source          # the published example, verbatim
    assert "orr_cnd_dit_cd" in source
    # set once, with no branch that swaps the type code for another value
    # (the docstring names it too, so only assignments are counted)
    assert source.count('"nmn_pr_tp_cd":') == 1
