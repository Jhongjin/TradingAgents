from datetime import date

from tradingagents.execution import BrokerAccountSnapshot, BrokerOrderResult
from tradingagents.harness import PipelineConfig
from tradingagents.harness.pipeline import _business_days_between, _evaluate_exits


def test_business_days_between_counts_weekdays_after_start():
    assert _business_days_between(date(2026, 9, 1), date(2026, 9, 8)) == 5  # Tue → next Tue
    assert _business_days_between(date(2026, 9, 8), date(2026, 9, 8)) == 0
    assert _business_days_between(date(2026, 9, 9), date(2026, 9, 8)) == 0


class HeldBroker:
    name = "held"
    is_paper = True
    quotes = {"005930": 66_000.0, "000660": 100_000.0, "035420": 101_000.0}

    def __init__(self):
        self.orders = []

    def quote(self, code):
        return self.quotes[code]

    def account_snapshot(self, prices=None):
        positions = {
            "005930": {"quantity": 10, "average_price": 70_000, "market_value": 660_000},  # -5.7% → stop loss
            "000660": {"quantity": 1, "average_price": 100_000, "market_value": 100_000},  # flat, held ~36 days → time exit
            "035420": {"quantity": 1, "average_price": 100_000, "market_value": 101_000},  # flat, recent → keep
        }
        return BrokerAccountSnapshot(broker=self.name, cash=5_000_000, equity=5_861_000, positions=positions)

    def place_order(self, order, *, price, dry_run=False):
        self.orders.append((order.ticker, order.reason, price, dry_run))
        return BrokerOrderResult(status="dry_run" if dry_run else "accepted", order=order, broker=self.name, message="ok")


def test_exits_use_broker_quote_and_holding_days():
    broker = HeldBroker()
    decisions = _evaluate_exits(
        broker,
        PipelineConfig(stop_loss_pct=0.05, take_profit_pct=0.10, max_holding_days=20, dry_run=False),
        {},
        None,
        entry_dates={"000660": date(2026, 7, 20), "035420": date(2026, 9, 7)},
        as_of=date(2026, 9, 9),
    )
    exited = {decision.code: decision for decision in decisions}
    assert set(exited) == {"005930", "000660"}
    assert exited["005930"].reasons[0] == "stop_loss"
    assert exited["000660"].reasons[0] == "max_holding_days"
    assert [order[0] for order in broker.orders] == ["005930", "000660"]
    assert broker.orders[0][2] == 66_000.0  # priced off the broker quote
    assert all(order[3] is False for order in broker.orders)


def test_exits_without_entry_dates_apply_only_price_rules():
    broker = HeldBroker()
    decisions = _evaluate_exits(broker, PipelineConfig(stop_loss_pct=0.05, take_profit_pct=0.10), {}, None, as_of=date(2026, 9, 9))
    assert [decision.code for decision in decisions] == ["005930"]
    assert broker.orders[0][3] is True  # default config is a dry run


def test_pipeline_config_validates_holding_days():
    import pytest

    with pytest.raises(ValueError):
        PipelineConfig(max_holding_days=0)
