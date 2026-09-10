"""Input models for TradingAgents persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping


PAPER_SIMULATION_ACCOUNT_NAME = "AI 가상매매"
PAPER_SIMULATION_LEGACY_ACCOUNT_NAME = "AI 모의투자"


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
    name: str = PAPER_SIMULATION_ACCOUNT_NAME
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
class HarnessRunInput:
    as_of_date: date
    mode: str = "paper"
    broker: str = "paper"
    dry_run: bool = True
    confirmer: str = "none"
    visibility: str = "public"
    status: str = "completed"
    markets: str = "KOSPI,KOSDAQ"
    universe_size: int = 0
    candidate_count: int = 0
    order_count: int = 0
    cash_before: Decimal | None = None
    cash_after: Decimal | None = None
    audit_sequence_start: int | None = None
    audit_sequence_end: int | None = None
    notes: list[str] = field(default_factory=list)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessDecisionInput:
    harness_run_id: str
    as_of_date: date
    ticker_code: str
    stage: str
    ticker_name: str | None = None
    market: str = "KR"
    screener_rank: int | None = None
    composite_score: float | None = None
    forecast_expected_return: float | None = None
    forecast_probability_up: float | None = None
    confirmation_rating: str | None = None
    confirmation_confidence: float | None = None
    confirmation_source: str | None = None
    quantity: int | None = None
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    order_status: str | None = None
    reasons: list[str] = field(default_factory=list)
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperAccountSnapshotInput:
    """One day of the harness paper account, with the benchmark at that date."""

    snapshot_date: date
    cash: Decimal
    holdings_value: Decimal
    equity: Decimal
    initial_cash: Decimal
    account_key: str = "harness"
    total_return: float | None = None
    realized_pnl: Decimal | None = None
    position_count: int = 0
    priced_count: int = 0
    benchmark_symbol: str | None = None
    benchmark_close: float | None = None
    benchmark_return: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessOutcomeInput:
    harness_decision_id: str
    harness_run_id: str
    ticker_code: str
    entry_date: date
    evaluated_at: date
    horizon_days: int
    ticker_name: str | None = None
    market: str = "KR"
    actual_holding_days: int | None = None
    benchmark_symbol: str | None = None
    raw_return: float | None = None
    benchmark_return: float | None = None
    alpha_return: float | None = None
    confirmation_rating: str | None = None
    confirmation_source: str | None = None
    status: str = "pending"
    error: str | None = None
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


@dataclass(frozen=True)
class SubscriptionInput:
    user_id: str
    plan: str = "free"
    status: str = "inactive"
    provider: str = "portone"
    customer_key: str | None = None
    billing_key: str | None = None
    trial_ends_at: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    last_payment_id: str | None = None
    last_payment_at: datetime | None = None
    failure_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BillingEventInput:
    event_type: str
    user_id: str | None = None
    subscription_id: str | None = None
    provider: str = "portone"
    payment_id: str | None = None
    amount: Decimal | None = None
    currency: str = "KRW"
    status: str | None = None
    message: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NotificationChannelInput:
    user_id: str
    channel: str = "telegram"
    external_id: str | None = None
    display_name: str | None = None
    link_code: str | None = None
    link_code_expires_at: datetime | None = None
    linked_at: datetime | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
