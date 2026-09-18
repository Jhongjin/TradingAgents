"""Borrowed positions: what is owed, when it is due, and how close the floor is."""

from datetime import date

from tradingagents.desk.margin import (
    DEFAULT_MAINTENANCE_PCT,
    margin_loans,
    margin_summary,
)

ACCOUNT = {"tot_aet_amt": 1_992_870, "tot_eal_amt": 1_870_080, "dca": 122_790,
           "mgg_rt": 200.782}
HOLDINGS = [
    {"iem_cd": "034020", "iem_nm": "두산에너빌리티", "eal_amt": 857_000,
     "lon_byn_dt": "20260909", "xrn_dt": "20261208", "wtm_rt": "30%",
     "lon_bnc_amt": 461_450},
    {"iem_cd": "088350", "iem_nm": "한화생명", "eal_amt": 1_013_080,
     "lon_byn_dt": "20260909", "xrn_dt": "20261208", "wtm_rt": "40%",
     "lon_bnc_amt": 499_660},
]
CASH_HOLDING = {"iem_cd": "005930", "iem_nm": "삼성전자", "eal_amt": 1_300_000,
                "lon_byn_dt": "", "xrn_dt": "00000000", "lon_bnc_amt": 0}


def test_the_loan_fields_are_read_off_a_live_response():
    loans = margin_loans(HOLDINGS)
    assert [loan.code for loan in loans] == ["034020", "088350"]
    assert loans[0].loan_amount == 461_450
    assert loans[0].opened_on == date(2026, 9, 9)
    assert loans[0].expires_on == date(2026, 12, 8)
    assert loans[0].deposit_rate == "30%"


def test_a_cash_holding_is_not_a_loan():
    assert margin_loans([CASH_HOLDING]) == []
    assert margin_summary(ACCOUNT, [CASH_HOLDING]) is None


def test_the_summary_adds_up_what_is_owed_and_counts_down_to_the_nearest_due_date():
    summary = margin_summary(ACCOUNT, HOLDINGS, today=date(2026, 9, 18))
    assert summary["loan_total"] == 961_110
    assert summary["next_due"] == "2026-12-08"
    assert summary["next_due_days"] == 81
    assert summary["ratio"] == 200.782
    assert summary["maintenance_pct"] == DEFAULT_MAINTENANCE_PCT
    assert summary["at_risk"] is False


def test_a_loan_close_to_expiry_is_flagged_so_it_is_not_noticed_on_the_day():
    summary = margin_summary(ACCOUNT, HOLDINGS, today=date(2026, 12, 1))
    assert summary["next_due_days"] == 7
    assert all(loan["due_soon"] for loan in summary["loans"])


def test_the_room_left_is_the_fall_the_holdings_can_take_not_the_ratio_gap():
    """Cash inside the assets does not fall with the market, so the two differ."""

    summary = margin_summary(ACCOUNT, HOLDINGS, today=date(2026, 9, 18))
    # assets may fall to 140/200.782 of where they are: about 30.3%
    # but that fall lands entirely on the holdings, which are smaller than assets
    assert 32.0 <= summary["room_pct"] <= 32.6
    assert summary["room_pct"] > (1 - 140 / 200.782) * 100


def test_an_account_already_under_the_floor_has_no_room_and_says_so():
    tight = dict(ACCOUNT, mgg_rt=135.0)
    summary = margin_summary(tight, HOLDINGS, today=date(2026, 9, 18))
    assert summary["at_risk"] is True
    assert summary["room_pct"] is None


def test_the_floor_is_a_setting_because_nh_does_not_return_it(monkeypatch):
    """It is a contract term, not an API field, so it must be correctable."""

    monkeypatch.setenv("TRADINGAGENTS_DESK_MAINTENANCE_PCT", "150")
    summary = margin_summary(ACCOUNT, HOLDINGS, today=date(2026, 9, 18))
    assert summary["maintenance_pct"] == 150.0
    assert summary["room_pct"] < 32.0          # a higher floor leaves less room

    monkeypatch.setenv("TRADINGAGENTS_DESK_MAINTENANCE_PCT", "나쁜값")
    assert margin_summary(ACCOUNT, HOLDINGS)["maintenance_pct"] == DEFAULT_MAINTENANCE_PCT


def test_a_missing_ratio_does_not_invent_one():
    summary = margin_summary({"tot_aet_amt": 1, "tot_eal_amt": 1}, HOLDINGS)
    assert summary["ratio"] is None
    assert summary["room_pct"] is None
    assert summary["at_risk"] is False
    assert summary["loan_total"] == 961_110    # the rest still works


def test_the_account_route_carries_the_margin_block_only_when_something_is_borrowed():
    from fastapi.testclient import TestClient
    from tradingagents.desk import create_desk_app

    class _Borrowed:
        def balance(self, account_no=None):
            return {"rsp_cd": "00166", "Output_0": ACCOUNT, "Output_1": HOLDINGS}

    class _Clear:
        def balance(self, account_no=None):
            return {"rsp_cd": "00166", "Output_0": ACCOUNT, "Output_1": [CASH_HOLDING]}

    for client, expected in ((_Borrowed(), True), (_Clear(), False)):
        app = create_desk_app(token="T0KEN", client_factory=lambda c=client: c)
        with TestClient(app, base_url="http://127.0.0.1:8787") as http:
            body = http.get("/api/account?t=T0KEN").json()
        assert (body["margin"] is not None) is expected


def test_the_panel_hides_itself_on_a_cash_account():
    from tradingagents.desk.page import render_desk

    page = render_desk(mode="live")
    assert 'id="margin-panel" hidden' in page
    assert "drawMargin" in page
    # the estimate is labelled as one on the page itself, not only in the code
    assert "개략치" in page
