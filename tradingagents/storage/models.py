"""Input models for TradingAgents persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class AnalysisRunInput:
    ticker_code: str
    trade_date: date
    ticker_name: str | None = None
    market: str = "KR"
    status: str = "pending"
    visibility: str = "public"
    user_id: str | None = None
    model_provider: str | None = None
    deep_model: str | None = None
    quick_model: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisRequestInput:
    ticker_code: str
    requested_trade_date: date
    user_id: str | None = None
    ticker_name: str | None = None
    market: str = "KR"
    status: str = "queued"
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentReportInput:
    analysis_run_id: str
    role: str
    content: str
    title: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TradeDecisionInput:
    analysis_run_id: str
    rating: str
    action: str
    target_weight: float | None = None
    rationale: str = ""
    raw_decision: str = ""


@dataclass(frozen=True)
class AnalysisOutcomeInput:
    analysis_run_id: str
    ticker_code: str
    trade_date: date
    evaluated_at: date
    horizon_days: int
    ticker_name: str | None = None
    market: str = "KR"
    actual_holding_days: int | None = None
    entry_close: Decimal | None = None
    exit_close: Decimal | None = None
    benchmark_symbol: str | None = None
    benchmark_entry_close: Decimal | None = None
    benchmark_exit_close: Decimal | None = None
    raw_return: float | None = None
    benchmark_return: float | None = None
    alpha_return: float | None = None
    decision_rating: str | None = None
    decision_action: str | None = None
    status: str = "pending"
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ManualTradeInput:
    portfolio_id: str
    ticker_code: str
    side: str
    trade_date: date
    price: Decimal
    quantity: int
    ticker_name: str | None = None
    market: str = "KR"
    fee: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    memo: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class PaperSimulationAccountInput:
    user_id: str
    name: str = "AI 모의투자"
    base_currency: str = "KRW"
    initial_cash: Decimal = Decimal("10000000")
    cash_balance: Decimal | None = None
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperSimulationPositionInput:
    account_id: str
    user_id: str
    ticker_code: str
    status: str
    quantity: int
    ticker_name: str | None = None
    market: str = "KR"
    analysis_run_id: str | None = None
    analysis_request_id: str | None = None
    entry_date: date | None = None
    entry_price: Decimal | None = None
    average_price: Decimal | None = None
    target_price: Decimal | None = None
    stop_price: Decimal | None = None
    exit_date: date | None = None
    exit_price: Decimal | None = None
    exit_reason: str | None = None
    realized_pnl: Decimal | None = None
    realized_return: float | None = None
    decision_rating: str | None = None
    decision_action: str | None = None
    target_weight: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperSimulationEventInput:
    account_id: str
    user_id: str
    event_type: str
    event_date: date
    ticker_code: str
    position_id: str | None = None
    analysis_run_id: str | None = None
    side: str | None = None
    price: Decimal | None = None
    quantity: int | None = None
    notional: Decimal | None = None
    commission: Decimal = Decimal("0")
    transaction_tax: Decimal = Decimal("0")
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
