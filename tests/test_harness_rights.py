"""Ex-dividend drops, and the stop-loss that should not fire on them."""

from datetime import date

from tradingagents.execution import BrokerAccountSnapshot, BrokerOrderResult
from tradingagents.harness import PipelineConfig
from tradingagents.harness.pipeline import _evaluate_exits
from tradingagents.harness.rights import ExRight, ex_rights_from_nh, holds_through

SCHEDULED = {"rsp_cd": "00166", "Output_0": [
    {"iem_cd": "004990", "iem_nm": "롯데지주", "rit_tp_cd": "01", "rit_tp_nm": "배당",
     "xgt_dt": "20260730", "bse_dt": "20260731", "rit_erc_end_dt": "00000000"},
    {"iem_cd": "005250", "iem_nm": "녹십자홀딩스", "rit_tp_cd": "01", "rit_tp_nm": "배당",
     "xgt_dt": "20260930", "bse_dt": "20261001"},
    {"iem_cd": "005930", "iem_nm": "삼성전자", "rit_tp_cd": "09", "rit_tp_nm": "유상증자",
     "xgt_dt": "20260730", "bse_dt": "20260731"},
]}


def test_the_dates_are_parsed_and_nhs_zero_date_means_nothing():
    rights = ex_rights_from_nh(SCHEDULED)
    assert rights["004990"].ex_date == date(2026, 7, 30)
    assert rights["004990"].base_date == date(2026, 7, 31)
    assert ex_rights_from_nh({"Output_0": [
        {"iem_cd": "000100", "rit_tp_nm": "배당", "xgt_dt": "00000000"}]})["000100"].ex_date is None


def test_a_dividend_holds_the_stop_only_on_the_day_it_comes_off():
    rights = ex_rights_from_nh(SCHEDULED)
    assert holds_through(rights, "004990", date(2026, 7, 30)) is not None
    assert holds_through(rights, "004990", date(2026, 7, 31)) is None
    assert holds_through(rights, "004990", date(2026, 7, 29)) is None


def test_a_rights_offering_is_not_a_reason_to_hold():
    """It changes the share count on its own schedule, not the price on one day."""

    rights = ex_rights_from_nh(SCHEDULED)
    assert holds_through(rights, "005930", date(2026, 7, 30)) is None


def test_a_ticker_with_nothing_due_and_an_empty_answer_are_both_just_no():
    rights = ex_rights_from_nh(SCHEDULED)
    assert holds_through(rights, "000660", date(2026, 7, 30)) is None
    assert holds_through({}, "004990", date(2026, 7, 30)) is None
    assert holds_through(None, "004990", date(2026, 7, 30)) is None


def test_the_nearest_date_wins_when_a_ticker_has_two_rights_due():
    rights = ex_rights_from_nh({"Output_0": [
        {"iem_cd": "004990", "rit_tp_nm": "배당", "xgt_dt": "20261230"},
        {"iem_cd": "004990", "rit_tp_nm": "배당", "xgt_dt": "20260630"},
    ]})
    assert rights["004990"].ex_date == date(2026, 6, 30)


def test_the_nested_shape_of_rights_held_is_read_too():
    """권리보유 puts its summary in Output_0 and the list in Output_1."""

    rights = ex_rights_from_nh({"Output_0": {"sta_dt": "20260318"},
                                "Output_1": [{"iem_cd": "473330", "iem_nm": "SOL 미국30년국채",
                                              "rit_tp_nm": "배당", "xgt_dt": "20260331"}]})
    assert rights["473330"].ex_date == date(2026, 3, 31)


class _Held:
    """One position, 7% under water, which is a stop under any normal reading."""

    name = "held"
    is_paper = True

    def __init__(self):
        self.orders = []

    def quote(self, code):
        return 93_000.0

    def account_snapshot(self, prices=None):
        return BrokerAccountSnapshot(
            broker=self.name, cash=1_000_000, equity=1_930_000,
            positions={"004990": {"quantity": 10, "average_price": 100_000,
                                  "market_value": 930_000}},
        )

    def place_order(self, order, *, price, dry_run=False):
        self.orders.append((order.ticker, order.reason))
        return BrokerOrderResult(status="accepted", order=order, broker=self.name, message="ok")


def test_the_stop_sits_out_the_ex_date_and_fires_the_next_day():
    """The whole point: a 7% drop that is a dividend leaving is not a 7% loss."""

    config = PipelineConfig(stop_loss_pct=0.05)
    rights = {"004990": ExRight("004990", "롯데지주", "배당", date(2026, 7, 30), date(2026, 7, 31))}

    broker = _Held()
    held = _evaluate_exits(broker, config, {"004990": 93_000}, None,
                           as_of=date(2026, 7, 30), ex_rights=rights)
    assert held == [] and broker.orders == []

    broker = _Held()
    sold = _evaluate_exits(broker, config, {"004990": 93_000}, None,
                           as_of=date(2026, 7, 31), ex_rights=rights)
    assert any("stop_loss" in reason for _, reason in broker.orders), sold


def test_without_any_rights_the_stop_behaves_exactly_as_before():
    broker = _Held()
    _evaluate_exits(broker, PipelineConfig(stop_loss_pct=0.05), {"004990": 93_000}, None,
                    as_of=date(2026, 7, 30))
    assert any("stop_loss" in reason for _, reason in broker.orders)


def test_a_dividend_does_not_rescue_a_position_from_the_holding_limit():
    """The hold is for the stop only. Time and take-profit are unaffected."""

    rights = {"004990": ExRight("004990", "롯데지주", "배당", date(2026, 7, 30), None)}
    broker = _Held()
    _evaluate_exits(broker, PipelineConfig(stop_loss_pct=0.99, max_holding_days=5), 
                    {"004990": 93_000}, None,
                    entry_dates={"004990": date(2026, 6, 1)},
                    as_of=date(2026, 7, 30), ex_rights=rights)
    assert any("max_holding_days" in reason for _, reason in broker.orders)
