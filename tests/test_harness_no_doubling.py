"""One name gets one slot, however many mornings the screen likes it.

에스엠 was bought twice in one week and stopped out twice, for 422,090원 and
425,216원 — two full slots in one company. Sizing capped each buy at a slot;
the mandate gate allowed the combined position up to its own, larger limit;
nothing compared the two.
"""

from tradingagents.execution import BrokerAccountSnapshot, BrokerOrderResult
from tradingagents.harness import PipelineConfig
from tradingagents.harness.pipeline import _process_candidate
from tradingagents.screener import ScreenerCandidate
from tradingagents.screener.factors import FactorScores


class _Account:
    name = "paper"
    is_paper = True

    def __init__(self, positions=None, equity=50_000_000.0, cash=50_000_000.0):
        self._positions = positions or {}
        self.equity = equity
        self.cash = cash
        self.orders = []

    def quote(self, code):
        return 50_000.0

    def account_snapshot(self, prices=None):
        return BrokerAccountSnapshot(broker=self.name, cash=self.cash,
                                     equity=self.equity, positions=self._positions)

    def place_order(self, order, *, price, dry_run=False):
        self.orders.append((order.ticker, order.quantity))
        return BrokerOrderResult(status="accepted", order=order, broker=self.name, message="ok")


def _candidate(code="041510", name="에스엠"):
    return ScreenerCandidate(
        rank=1, code=code, name=name, market="KOSDAQ", close=50_000.0,
        market_cap=1e12, trading_value=5e9, per=12.0, pbr=1.2, dividend_yield=0.01,
        factors=FactorScores(momentum_20d=0.05, momentum_60d=0.10, momentum_120d=0.20,
                             ma_alignment=1.0, rsi_14=55.0, volume_surge=1.2,
                             volatility_20d=0.02, distance_from_high_60d=-0.03,
                             composite=1.0, labels=["test"]),
        reasons=["test"],
    )


def _points():
    return [{"date": f"2026-{month:02d}-{day:02d}",
             "close": 40_000.0 * (1.002 ** (month * 28 + day)), "volume": 400_000}
            for month in range(1, 10) for day in range(1, 29)]


def _run(broker, config=None):
    """The entry path, with the screen, the forecast and the confirmer stubbed out."""

    from tradingagents.forecast.naive import NaiveForecaster

    return _process_candidate(
        _candidate(),
        config=config or PipelineConfig(require_llm_confirmation=False),
        fetcher=lambda code, start, end: _points(),
        forecaster=NaiveForecaster(),
        confirmer=None,
        broker=broker,
        ledger=None,
        start_date="2026-01-01",
        end_date="2026-09-18",
        current_prices={"041510": 50_000.0},
    )


def test_the_sizing_cap_and_the_gate_cap_are_not_the_same_number():
    """The hole this closes: 10% per buy, 25% allowed in total."""

    config = PipelineConfig()
    slot = 1.0 / config.mandate.max_positions
    assert slot < config.mandate.max_position_weight       # the gap that let it stack


def test_a_name_already_at_its_slot_is_refused_rather_than_doubled():
    held = {"041510": {"quantity": 100, "average_price": 50_000, "market_value": 5_000_000}}
    broker = _Account(positions=held)                      # 5,000,000 of 50,000,000 = one slot

    decision = _run(broker)

    assert decision.stage == "gate_rejected"
    assert "이미" in " ".join(decision.reasons)
    assert broker.orders == []


def test_a_name_holding_half_a_slot_gets_only_the_other_half():
    held = {"041510": {"quantity": 50, "average_price": 50_000, "market_value": 2_500_000}}
    broker = _Account(positions=held)

    decision = _run(broker)
    sizing = decision.sizing or {}

    # room left is 10% - 5% = 5% of 50,000,000 = 2,500,000, so 50 shares at 50,000
    assert decision.stage != "gate_rejected"
    assert 0 < sizing.get("quantity", 0) <= 50


def test_a_name_not_held_still_gets_a_full_slot():
    broker = _Account()
    decision = _run(broker)
    sizing = decision.sizing or {}

    assert decision.stage != "gate_rejected"
    assert sizing.get("quantity", 0) > 50                  # a whole slot, not a half


def test_two_mornings_in_a_row_cannot_put_a_fifth_of_the_account_in_one_name():
    """The 에스엠 case, played forward."""

    broker = _Account()
    first = _run(broker)
    bought = (first.sizing or {}).get("quantity", 0)
    assert bought > 0

    # the account now holds what the first morning bought
    value = bought * 50_000
    broker._positions = {"041510": {"quantity": bought, "average_price": 50_000,
                                    "market_value": value}}
    second = _run(broker)
    added = (second.sizing or {}).get("quantity", 0) if second.stage != "gate_rejected" else 0

    total_weight = (value + added * 50_000) / broker.equity
    assert total_weight <= 1.0 / PipelineConfig().mandate.max_positions + 1e-6
