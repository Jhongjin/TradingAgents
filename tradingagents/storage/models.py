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
