"""Our record against the broker's, and what counts as a difference."""

from tradingagents.desk.reconcile import (
    broker_trades,
    cash_movements,
    our_trades,
    reconcile,
)
from tradingagents.execution.audit import AuditLedger

RAW = {"rsp_cd": "00166", "Output_0": [
    {"trd_dt": "20260907", "iem_cd": "", "iem_nm": "", "trd_qty": 0.0,
     "trd_amt": 1_000_000.0, "sps_cd_krl_anm": "이체입금"},
    {"trd_dt": "20260909", "iem_cd": "034020", "iem_nm": "두산에너빌리티", "trd_qty": 10.0,
     "trd_uit_pr": 83_900.0, "trd_amt": 839_000.0,
     "sps_cd_krl_anm": "신용대출매수(코스피)(유통융자)"},
    {"trd_dt": "20260910", "iem_cd": "005930", "iem_nm": "삼성전자", "trd_qty": 5.0,
     "trd_uit_pr": 260_000.0, "trd_amt": 1_300_000.0, "sps_cd_krl_anm": "코스피매도"},
]}


def _book(tmp_path, rows):
    book = AuditLedger(str(tmp_path / "orders.jsonl"))
    for row in rows:
        book.append("desk.order", row)
    return book


def _order(day, code, side, quantity, *, stage="accepted", mode="live"):
    return {"stage": stage, "date": day, "mode": mode, "side": side, "code": code,
            "quantity": quantity, "price": 1_000, "amount": quantity * 1_000}


def test_a_deposit_is_not_a_trade_and_does_not_look_like_a_missing_one():
    trades = broker_trades(RAW)
    assert [trade.code for trade in trades] == ["034020", "005930"]

    cash = cash_movements(RAW)
    assert len(cash) == 3        # the cash view keeps everything, including the deposit


def test_the_side_is_read_out_of_the_korean_label_however_it_is_routed():
    trades = {trade.code: trade.side for trade in broker_trades(RAW)}
    assert trades["034020"] == "buy"      # 신용대출매수(코스피)(유통융자)
    assert trades["005930"] == "sell"     # 코스피매도


def test_matching_records_agree_and_the_price_difference_is_not_a_mismatch(tmp_path):
    """Our record holds the limit sent; the broker's holds the price it filled at."""

    book = _book(tmp_path, [_order("2026-09-09", "034020", "buy", 10),
                            _order("2026-09-10", "005930", "sell", 5)])
    result = reconcile(broker_trades(RAW), our_trades(book, start="2026-09-01", end="2026-09-30"))

    assert result.clean
    assert len(result.agreed) == 2


def test_an_order_only_the_broker_knows_about_is_reported(tmp_path):
    """A trade placed in the broker's own app, or one our ledger lost."""

    book = _book(tmp_path, [_order("2026-09-09", "034020", "buy", 10)])
    result = reconcile(broker_trades(RAW), our_trades(book, start="2026-09-01", end="2026-09-30"))

    assert not result.clean
    assert [row["code"] for row in result.broker_only] == ["005930"]
    assert result.broker_only[0]["our_quantity"] is None


def test_an_order_only_we_know_about_is_reported(tmp_path):
    """The dangerous direction: we believe we traded and the broker does not."""

    book = _book(tmp_path, [_order("2026-09-09", "034020", "buy", 10),
                            _order("2026-09-10", "005930", "sell", 5),
                            _order("2026-09-11", "000660", "buy", 3)])
    result = reconcile(broker_trades(RAW), our_trades(book, start="2026-09-01", end="2026-09-30"))

    assert [row["code"] for row in result.ours_only] == ["000660"]


def test_a_quantity_that_does_not_line_up_is_its_own_verdict(tmp_path):
    book = _book(tmp_path, [_order("2026-09-09", "034020", "buy", 10),
                            _order("2026-09-10", "005930", "sell", 4)])
    result = reconcile(broker_trades(RAW), our_trades(book, start="2026-09-01", end="2026-09-30"))

    assert len(result.quantity_differs) == 1
    row = result.quantity_differs[0]
    assert row["broker_quantity"] == 5 and row["our_quantity"] == 4


def test_two_of_ours_on_one_day_add_up_against_one_broker_row(tmp_path):
    """A split order is one trade to the broker and two lines to us."""

    book = _book(tmp_path, [_order("2026-09-09", "034020", "buy", 6),
                            _order("2026-09-09", "034020", "buy", 4),
                            _order("2026-09-10", "005930", "sell", 5)])
    result = reconcile(broker_trades(RAW), our_trades(book, start="2026-09-01", end="2026-09-30"))
    assert result.clean


def test_an_order_whose_fate_is_unknown_is_not_counted_as_a_trade(tmp_path):
    """A 'sent' with no ending is the case this comparison exists to surface."""

    book = _book(tmp_path, [_order("2026-09-09", "034020", "buy", 10, stage="sent"),
                            _order("2026-09-09", "034020", "buy", 10, stage="failed")])
    assert our_trades(book, start="2026-09-01", end="2026-09-30") == []


def test_the_other_account_s_orders_are_not_missing_trades(tmp_path):
    """One ledger holds both accounts; comparing all of it against one is noise."""

    book = _book(tmp_path, [_order("2026-09-09", "034020", "buy", 10, mode="live"),
                            _order("2026-09-10", "005930", "sell", 5, mode="paper")])

    both = our_trades(book, start="2026-09-01", end="2026-09-30")
    assert len(both) == 2

    live_only = our_trades(book, start="2026-09-01", end="2026-09-30", mode="live")
    assert [trade.code for trade in live_only] == ["034020"]


def test_a_cancel_moves_nothing_and_is_left_out(tmp_path):
    book = _book(tmp_path, [_order("2026-09-09", "034020", "cancel", 10),
                            _order("2026-09-09", "034020", "reserve-cancel", 10)])
    assert our_trades(book, start="2026-09-01", end="2026-09-30") == []


def test_orders_outside_the_window_are_not_dragged_in(tmp_path):
    book = _book(tmp_path, [_order("2026-08-31", "034020", "buy", 10),
                            _order("2026-10-01", "034020", "buy", 10)])
    assert our_trades(book, start="2026-09-01", end="2026-09-30") == []


def test_the_reconcile_route_is_behind_the_guard():
    from fastapi.testclient import TestClient
    from tradingagents.desk import create_desk_app

    app = create_desk_app(token="T0KEN", client_factory=lambda: None)
    with TestClient(app, base_url="http://127.0.0.1:8787") as http:
        assert http.get("/api/reconcile").status_code == 401
