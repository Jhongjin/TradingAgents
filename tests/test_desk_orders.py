"""What the desk refuses before the broker is asked, and what it writes after."""

import json

from pathlib import Path

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


_SIZE_BEFORE = (Path.home() / ".tradingagents" / "desk" / "orders.jsonl")
_SIZE_BEFORE = _SIZE_BEFORE.stat().st_size if _SIZE_BEFORE.exists() else 0


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


EXECUTIONS = {"rsp_cd": "XA102", "rsp_msg": "정상적으로 조회가 완료되었습니다", "Output_0": [
    {"itg_orr_no": 29, "iem_cd": "005930", "iem_nm": "삼성전자", "sby_dit_cd_nm": "현금매수",
     "orr_qty": 10, "orr_pr": 260000.0, "tot_cns_qty": 4, "cns_avg_uit_pr": 259500.0,
     "can_qty": 6, "orr_rjt_rsn_cd_nm": "정상"},
]}


class _Book(_Broker):
    def executions(self, *, on=None, account_no=None):
        if self.fail:
            raise RuntimeError(self.fail)
        return EXECUTIONS

    def cancel_order(self, *, order_no, code, quantity=None, account_no=None):
        self.sent.append({"cancel": order_no, "code": code, "quantity": quantity})
        if self.fail:
            raise RuntimeError(self.fail)
        return {"rsp_cd": "00192", "rsp_msg": "취소주문이 완료되었습니다."}


def test_todays_orders_show_what_filled_and_what_can_still_be_cancelled(tmp_path, monkeypatch):
    with _desk(_Book(), tmp_path, monkeypatch) as http:
        row = http.get("/api/orders?t=T").json()["orders"][0]

    assert row["order_no"] == 29 and row["name"] == "삼성전자"
    assert row["quantity"] == 10 and row["filled"] == 4
    assert row["filled_price"] == 259_500
    # from the broker's own can_qty, not ordered-minus-filled: a partly
    # cancelled order would make that subtraction wrong
    assert row["cancellable"] == 6
    assert row["status"] == "정상"


def test_cancelling_needs_no_cap_and_no_typed_confirmation(tmp_path, monkeypatch):
    """Every other guard slows down committing money; this is the way out."""

    broker = _Book()
    with _desk(broker, tmp_path, monkeypatch) as http:
        result = http.post("/api/cancel?t=T", json={"order_no": 29, "code": "005930"}).json()

    assert result["ok"] is True
    assert broker.sent == [{"cancel": 29, "code": "005930", "quantity": None}]

    lines = [json.loads(line) for line in (tmp_path / "orders.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [line["payload"]["stage"] for line in lines] == ["sent", "accepted"]
    assert lines[0]["payload"]["side"] == "cancel"
    # a cancel commits nothing, so it must not eat the day's budget
    assert today_spent(AuditLedger(tmp_path / "orders.jsonl")) == (0, 0)


def test_a_cancel_takes_a_name_and_refuses_an_ambiguous_one(tmp_path, monkeypatch):
    broker = _Book()
    with _desk(broker, tmp_path, monkeypatch) as http:
        assert http.post("/api/cancel?t=T", json={"order_no": 29, "code": "가온전선"}).json()["ok"]
        assert broker.sent[-1]["code"] == "000500"

        ambiguous = http.post("/api/cancel?t=T", json={"order_no": 29, "code": "삼성"})
        assert ambiguous.status_code == 404
        missing = http.post("/api/cancel?t=T", json={"code": "005930"})
        assert missing.status_code == 400 and "주문번호" in missing.json()["error"]


def test_a_failed_cancel_is_recorded_with_its_reason(tmp_path, monkeypatch):
    with _desk(_Book(fail="이미 체결된 주문입니다"), tmp_path, monkeypatch) as http:
        response = http.post("/api/cancel?t=T", json={"order_no": 29, "code": "005930"})
    assert response.status_code == 502
    lines = [json.loads(line) for line in (tmp_path / "orders.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [line["payload"]["stage"] for line in lines] == ["sent", "failed"]


def test_a_success_code_that_is_not_zero_prefixed_is_still_a_success():
    """XA102 means 정상적으로 조회가 완료되었습니다, and read as an error it broke the page."""

    from tradingagents.execution.nh_client import SUCCESS_PREFIXES

    assert "XA102".startswith(SUCCESS_PREFIXES)
    assert "00192".startswith(SUCCESS_PREFIXES)         # 취소완료
    assert "00164".startswith(SUCCESS_PREFIXES)         # 정정완료
    # and the shapes that are not: an unknown code stays a failure on purpose
    assert not "IGW40011".startswith(SUCCESS_PREFIXES)
    assert not "14580".startswith(SUCCESS_PREFIXES)
    assert not "11165".startswith(SUCCESS_PREFIXES)


def test_the_desk_ledger_env_var_is_the_one_the_desk_actually_reads(tmp_path, monkeypatch):
    """A redirect that silently does not redirect writes fake orders into the real book.

    AuditLedger.from_env only knows TRADINGAGENTS_AUDIT_LOG_PATH. A test that
    set TRADINGAGENTS_DESK_LEDGER and believed it had moved the file wrote five
    runs of pretend live orders into ~/.tradingagents/desk/orders.jsonl, where
    they turned up as unexplained trades in the reconciliation.
    """

    from tradingagents.desk.orders import ledger

    target = tmp_path / "desk.jsonl"
    monkeypatch.setenv("TRADINGAGENTS_DESK_LEDGER", str(target))
    monkeypatch.delenv("TRADINGAGENTS_AUDIT_LOG_PATH", raising=False)

    book = ledger()
    book.append("desk.order", {"stage": "sent", "code": "005930"})
    assert target.exists()

    home_book = Path.home() / ".tradingagents" / "desk" / "orders.jsonl"
    assert not home_book.exists() or home_book.stat().st_size == _SIZE_BEFORE


def test_the_audit_variable_still_works_when_the_desk_one_is_unset(tmp_path, monkeypatch):
    from tradingagents.desk.orders import ledger

    target = tmp_path / "audit.jsonl"
    monkeypatch.delenv("TRADINGAGENTS_DESK_LEDGER", raising=False)
    monkeypatch.setenv("TRADINGAGENTS_AUDIT_LOG_PATH", str(target))

    ledger().append("desk.order", {"stage": "sent", "code": "005930"})
    assert target.exists()
