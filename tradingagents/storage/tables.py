"""SQLAlchemy table definitions for TradingAgents storage."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)


metadata = MetaData()

analysis_runs = Table(
    "analysis_runs",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("user_id", Uuid(as_uuid=False), nullable=True),
    Column("ticker_code", String(12), nullable=False, index=True),
    Column("ticker_name", String(120), nullable=True),
    Column("market", String(32), nullable=False, default="KR"),
    Column("trade_date", Date, nullable=False, index=True),
    Column("status", String(32), nullable=False, default="pending"),
    Column("visibility", String(16), nullable=False, default="public"),
    Column("model_provider", String(64), nullable=True),
    Column("deep_model", String(128), nullable=True),
    Column("quick_model", String(128), nullable=True),
    Column("metadata_json", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)

agent_reports = Table(
    "agent_reports",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("analysis_run_id", Uuid(as_uuid=False), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
    Column("role", String(64), nullable=False),
    Column("title", String(160), nullable=True),
    Column("content", Text, nullable=False),
    Column("metadata_json", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("analysis_run_id", "role", name="uq_agent_reports_run_role"),
)

trade_decisions = Table(
    "trade_decisions",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("analysis_run_id", Uuid(as_uuid=False), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
    Column("rating", String(64), nullable=False),
    Column("action", String(64), nullable=False),
    Column("target_weight", Float, nullable=True),
    Column("rationale", Text, nullable=False, default=""),
    Column("raw_decision", Text, nullable=False, default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("analysis_run_id", name="uq_trade_decisions_run"),
)

manual_portfolios = Table(
    "manual_portfolios",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("user_id", Uuid(as_uuid=False), nullable=False, index=True),
    Column("name", String(120), nullable=False),
    Column("base_currency", String(8), nullable=False, default="KRW"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

manual_trades = Table(
    "manual_trades",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("portfolio_id", Uuid(as_uuid=False), ForeignKey("manual_portfolios.id", ondelete="CASCADE"), nullable=False),
    Column("ticker_code", String(12), nullable=False, index=True),
    Column("ticker_name", String(120), nullable=True),
    Column("market", String(32), nullable=False, default="KR"),
    Column("side", String(8), nullable=False),
    Column("trade_date", Date, nullable=False, index=True),
    Column("price", Numeric(18, 4), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("fee", Numeric(18, 4), nullable=False, default=0),
    Column("tax", Numeric(18, 4), nullable=False, default=0),
    Column("memo", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

manual_price_targets = Table(
    "manual_price_targets",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("portfolio_id", Uuid(as_uuid=False), ForeignKey("manual_portfolios.id", ondelete="CASCADE"), nullable=False),
    Column("ticker_code", String(12), nullable=False, index=True),
    Column("target_price", Numeric(18, 4), nullable=True),
    Column("stop_price", Numeric(18, 4), nullable=True),
    Column("memo", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("portfolio_id", "ticker_code", name="uq_manual_price_targets_portfolio_ticker"),
)

manual_watchlists = Table(
    "manual_watchlists",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("user_id", Uuid(as_uuid=False), nullable=False, index=True),
    Column("name", String(120), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

manual_watchlist_items = Table(
    "manual_watchlist_items",
    metadata,
    Column("id", Uuid(as_uuid=False), primary_key=True),
    Column("watchlist_id", Uuid(as_uuid=False), ForeignKey("manual_watchlists.id", ondelete="CASCADE"), nullable=False),
    Column("ticker_code", String(12), nullable=False, index=True),
    Column("ticker_name", String(120), nullable=True),
    Column("market", String(32), nullable=False, default="KR"),
    Column("memo", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("watchlist_id", "ticker_code", name="uq_manual_watchlist_items_watchlist_ticker"),
)
