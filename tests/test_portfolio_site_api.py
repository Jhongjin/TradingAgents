from datetime import date
from decimal import Decimal

import pytest

from tradingagents.site import build_manual_portfolio_payload
from tradingagents.storage import ManualTradeInput, StorageRepository, create_storage_engine


USER_ID = "00000000-0000-0000-0000-000000000001"


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def _portfolio_with_samsung(repo: StorageRepository) -> str:
    portfolio_id = repo.create_manual_portfolio(user_id=USER_ID, name="Main")
    repo.add_manual_trade(
        ManualTradeInput(
            portfolio_id=portfolio_id,
            ticker_code="005930",
            side="buy",
            trade_date=date(2026, 1, 2),
            price=Decimal("70000"),
            quantity=10,
            fee=Decimal("100"),
        )
    )
    repo.add_manual_trade(
        ManualTradeInput(
            portfolio_id=portfolio_id,
            ticker_code="005930",
            side="buy",
            trade_date=date(2026, 1, 5),
            price=Decimal("72000"),
            quantity=5,
            fee=Decimal("100"),
        )
    )
    repo.add_manual_trade(
        ManualTradeInput(
            portfolio_id=portfolio_id,
            ticker_code="005930",
            side="sell",
            trade_date=date(2026, 1, 6),
            price=Decimal("73000"),
            quantity=4,
            fee=Decimal("50"),
            tax=Decimal("584"),
        )
    )
    return portfolio_id


def test_manual_portfolio_payload_calculates_summary_and_alerts():
    repo = _repo()
    portfolio_id = _portfolio_with_samsung(repo)
    repo.set_price_target(
        portfolio_id=portfolio_id,
        ticker_code="005930",
        target_price=Decimal("82000"),
        stop_price=Decimal("65000"),
    )

    payload = build_manual_portfolio_payload(
        repo,
        portfolio_id,
        current_prices={"005930.KS": Decimal("83000")},
    )

    position = payload["positions"][0]
    assert payload["pricing_status"] == "complete"
    assert payload["trade_count"] == 3
    assert [trade["side"] for trade in payload["trades"]] == ["sell", "buy", "buy"]
    assert payload["trades"][0]["trade_date"] == "2026-01-06"
    assert payload["totals"]["position_count"] == 1
    assert payload["totals"]["invested_cost"] == 777480.0
    assert payload["totals"]["market_value"] == 913000.0
    assert payload["totals"]["unrealized_pnl"] == 135520.0
    assert payload["totals"]["realized_pnl"] == 8646.0
    assert payload["totals"]["total_pnl"] == 144166.0
    assert position["ticker_name"] == "삼성전자"
    assert position["weight"] == 1.0
    assert position["target_price"] == 82000.0
    assert position["stop_price"] == 65000.0
    assert position["target_memo"] is None
    assert position["target_hit"] is True
    assert position["stop_hit"] is False
    assert payload["alerts"] == [
        {
            "ticker_code": "005930",
            "type": "target_hit",
            "message": "Current price is at or above the user-entered target price.",
        }
    ]


def test_manual_portfolio_payload_marks_partial_pricing():
    repo = _repo()
    portfolio_id = _portfolio_with_samsung(repo)
    repo.add_manual_trade(
        ManualTradeInput(
            portfolio_id=portfolio_id,
            ticker_code="000660",
            side="buy",
            trade_date=date(2026, 1, 2),
            price=Decimal("130000"),
            quantity=2,
        )
    )

    payload = build_manual_portfolio_payload(
        repo,
        portfolio_id,
        current_prices={"005930": Decimal("74000")},
    )

    assert payload["pricing_status"] == "partial"
    assert payload["totals"]["position_count"] == 2
    assert payload["totals"]["priced_position_count"] == 1
    assert payload["totals"]["market_value"] is None
    assert payload["totals"]["unrealized_pnl"] is None
    assert payload["positions"][0]["ticker_code"] == "000660"
    assert payload["positions"][0]["current_price"] is None


def test_manual_portfolio_payload_rejects_non_positive_current_price():
    repo = _repo()
    portfolio_id = _portfolio_with_samsung(repo)

    with pytest.raises(ValueError, match="current_prices values must be positive"):
        build_manual_portfolio_payload(repo, portfolio_id, current_prices={"005930": 0})
