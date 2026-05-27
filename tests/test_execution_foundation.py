import pandas as pd
import pytest

from tradingagents.execution import (
    BacktestEngine,
    KISConfig,
    KoreaTradingRules,
    PaperBroker,
    PaperSimulationConfig,
    RiskLimits,
    SignalPolicy,
    simulate_single_position,
    signal_from_decision,
)
from tradingagents.execution.models import OrderSide


def test_signal_from_decision_maps_pm_rating_to_target():
    signal = signal_from_decision("nvda", "**Rating**: Overweight\nBuild gradually.")

    assert signal.ticker == "NVDA"
    assert signal.rating == "Overweight"
    assert signal.action == "increase"
    assert signal.target_weight == SignalPolicy().overweight_weight


def test_paper_broker_buys_and_exits_position():
    broker = PaperBroker.with_limits(initial_cash=10_000, limits=RiskLimits(max_position_weight=0.5))

    buy = signal_from_decision("MSFT", "Rating: Buy")
    buy_fill = broker.rebalance(buy, price=100)
    assert buy_fill is not None
    assert buy_fill.order.side == OrderSide.BUY
    assert broker.portfolio.positions["MSFT"].quantity == 25

    sell = signal_from_decision("MSFT", "Rating: Sell")
    sell_fill = broker.rebalance(sell, price=110)
    assert sell_fill is not None
    assert sell_fill.order.side == OrderSide.SELL
    assert "MSFT" not in broker.portfolio.positions


def test_risk_limits_cap_target_weight():
    broker = PaperBroker.with_limits(initial_cash=10_000, limits=RiskLimits(max_position_weight=0.10))

    fill = broker.rebalance(signal_from_decision("AAPL", "Rating: Buy"), price=100)

    assert fill is not None
    assert fill.quantity == 10


def test_backtest_runs_from_date_keyed_decisions():
    prices = pd.DataFrame(
        {
            "Date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "Close": [100, 110, 120],
        }
    )
    engine = BacktestEngine(initial_cash=10_000, risk_limits=RiskLimits(max_position_weight=0.25))

    result = engine.run("NVDA", prices, {"2026-01-01": "Rating: Buy"})

    assert len(result.fills) == 1
    assert result.equity_curve.iloc[-1]["quantity"] == 25
    assert result.final_equity == 10_500
    assert result.total_return == pytest.approx(0.05)


def test_backtest_can_run_in_krw():
    prices = pd.DataFrame(
        {
            "Date": ["2026-01-01", "2026-01-02"],
            "Close": [70_000, 71_000],
        }
    )
    engine = BacktestEngine(
        initial_cash=10_000_000,
        risk_limits=RiskLimits(max_position_weight=0.25),
        currency="KRW",
    )

    result = engine.run("005930", prices, {"2026-01-01": "Rating: Buy"})

    assert result.equity_curve.iloc[-1]["currency"] == "KRW"
    assert result.final_equity > 10_000_000


def test_paper_broker_can_round_krw_execution_price_to_tick():
    broker = PaperBroker.with_limits(
        initial_cash=10_000_000,
        limits=RiskLimits(max_position_weight=0.25),
        slippage_bps=3,
        currency="KRW",
        execution_rules=KoreaTradingRules(),
    )

    fill = broker.rebalance(signal_from_decision("005930", "Rating: Buy"), price=71_055)

    assert fill is not None
    assert fill.price == 71_100


def test_krw_backtest_uses_korean_tick_rounding_by_default():
    prices = pd.DataFrame(
        {
            "Date": ["2026-01-01", "2026-01-02"],
            "Close": [71_055, 71_200],
        }
    )
    engine = BacktestEngine(
        initial_cash=10_000_000,
        risk_limits=RiskLimits(max_position_weight=0.25),
        slippage_bps=3,
        currency="KRW",
    )

    result = engine.run("005930", prices, {"2026-01-01": "Rating: Buy"})

    assert result.fills[0].price == 71_100


def test_krw_backtest_applies_sell_side_transaction_tax():
    prices = pd.DataFrame(
        {
            "Date": ["2026-01-01", "2026-01-02"],
            "Close": [70_000, 72_000],
        }
    )
    engine = BacktestEngine(
        initial_cash=10_000_000,
        risk_limits=RiskLimits(max_position_weight=0.25),
        currency="KRW",
    )

    result = engine.run("005930", prices, {"2026-01-01": "Rating: Buy", "2026-01-02": "Rating: Sell"})

    assert len(result.fills) == 2
    assert result.fills[1].transaction_tax == pytest.approx(72_000 * 35 * 0.002)
    assert result.final_equity == pytest.approx(10_064_960)


def test_single_position_simulator_enters_and_exits_on_take_profit():
    signal = signal_from_decision("005930", "Rating: Buy")
    result = simulate_single_position(
        signal,
        [
            {"date": "2026-05-05", "close": 70_000},
            {"date": "2026-05-06", "close": 73_000},
            {"date": "2026-05-07", "close": 76_000},
        ],
        config=PaperSimulationConfig(slippage_bps=0),
    )

    assert result.status == "closed"
    assert result.entry_date == "2026-05-05"
    assert result.exit_date == "2026-05-07"
    assert result.exit_reason == "take_profit"
    assert [event["side"] for event in result.events] == ["buy", "sell"]
    assert result.events[0]["quantity"] == 35
    assert result.trade_return == pytest.approx(76_000 / 70_000 - 1)
    assert result.final_equity == pytest.approx(10_204_680)


def test_single_position_simulator_skips_hold_signal():
    result = simulate_single_position(
        signal_from_decision("005930", "Rating: Hold"),
        [
            {"date": "2026-05-05", "close": 70_000},
            {"date": "2026-05-06", "close": 71_000},
        ],
    )

    assert result.status == "skipped"
    assert result.message == "signal_did_not_open_position"


def test_korean_trading_rules_tick_and_limit_prices():
    rules = KoreaTradingRules()

    assert rules.tick_size(71_000) == 100
    assert rules.round_price(71_055, OrderSide.BUY) == 71_100
    assert rules.round_price(71_055, OrderSide.SELL) == 71_000
    assert rules.limit_price(70_000, OrderSide.BUY) == 91_000
    assert rules.price_limits(9_940) == (6_960, 12_920)
    assert rules.transaction_tax_rate("005930") == pytest.approx(0.002)
    assert rules.transaction_tax_rate("KONEX") == pytest.approx(0.001)


def test_kis_config_reads_env_aliases(monkeypatch):
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678")
    monkeypatch.setenv("KIS_ACCOUNT_PRODUCT_CODE", "01")
    monkeypatch.setenv("KIS_APP_KEY", "key")
    monkeypatch.setenv("KIS_APP_SECRET", "secret")
    monkeypatch.setenv("KIS_IS_PAPER", "true")

    config = KISConfig.from_env()

    assert config.cano == "12345678"
    assert config.acnt_prdt_cd == "01"
    assert config.is_configured()
    config.validate_for_paper()


def test_kis_config_rejects_common_product_code_mistake():
    config = KISConfig(
        account_no="12345678",
        account_product_code="0626335",
        app_key="key",
        app_secret="secret",
        is_paper=True,
    )

    with pytest.raises(ValueError, match="product code must be exactly 2 digits"):
        config.validate_for_paper()
