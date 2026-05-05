"""Repository layer for analysis runs and manual portfolios."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
from typing import Any
from uuid import UUID
from uuid import uuid4

from sqlalchemy import Engine, create_engine, desc, insert, select, update

from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker

from .models import AgentReportInput, AnalysisRunInput, ManualTradeInput, TradeDecisionInput
from .portfolio import ManualPosition, calculate_manual_positions
from .tables import (
    agent_reports,
    analysis_runs,
    manual_portfolios,
    manual_price_targets,
    manual_trades,
    metadata,
    trade_decisions,
)


def create_storage_engine(database_url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine from DATABASE_URL or an in-memory SQLite DB."""

    url = database_url or os.getenv("DATABASE_URL") or "sqlite+pysqlite:///:memory:"
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return create_engine(url, echo=echo, future=True)


class StorageRepository:
    """Small persistence facade used by future web/API layers."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def create_schema(self) -> None:
        """Create local tables.

        Use the Supabase migration for production Postgres so RLS policies are
        applied. This method is mainly for tests and local development.
        """

        metadata.create_all(self.engine)

    def create_analysis_run(self, data: AnalysisRunInput) -> str:
        _validate_visibility(data.visibility)
        _validate_optional_uuid(data.user_id, "analysis user_id")
        run_id = _id()
        values = {
            "id": run_id,
            "user_id": data.user_id,
            "ticker_code": data.ticker_code,
            "ticker_name": data.ticker_name,
            "market": data.market,
            "trade_date": data.trade_date,
            "status": data.status,
            "visibility": data.visibility,
            "model_provider": data.model_provider,
            "deep_model": data.deep_model,
            "quick_model": data.quick_model,
            "metadata_json": dict(data.metadata),
        }
        with self.engine.begin() as conn:
            conn.execute(insert(analysis_runs).values(**values))
        return run_id

    def complete_analysis_run(self, analysis_run_id: str, *, status: str = "completed") -> None:
        _validate_uuid(analysis_run_id, "analysis_run_id")
        with self.engine.begin() as conn:
            conn.execute(
                update(analysis_runs)
                .where(analysis_runs.c.id == analysis_run_id)
                .values(status=status, completed_at=datetime.now(timezone.utc))
            )

    def add_agent_report(self, data: AgentReportInput) -> str:
        _validate_uuid(data.analysis_run_id, "analysis_run_id")
        report_id = _id()
        with self.engine.begin() as conn:
            conn.execute(
                insert(agent_reports).values(
                    id=report_id,
                    analysis_run_id=data.analysis_run_id,
                    role=data.role,
                    title=data.title,
                    content=data.content,
                    metadata_json=dict(data.metadata),
                )
            )
        return report_id

    def record_trade_decision(self, data: TradeDecisionInput) -> str:
        _validate_uuid(data.analysis_run_id, "analysis_run_id")
        decision_id = _id()
        with self.engine.begin() as conn:
            conn.execute(
                insert(trade_decisions).values(
                    id=decision_id,
                    analysis_run_id=data.analysis_run_id,
                    rating=data.rating,
                    action=data.action,
                    target_weight=data.target_weight,
                    rationale=data.rationale,
                    raw_decision=data.raw_decision,
                )
            )
        return decision_id

    def get_analysis_bundle(self, analysis_run_id: str) -> dict[str, Any] | None:
        _validate_uuid(analysis_run_id, "analysis_run_id")
        with self.engine.begin() as conn:
            run = conn.execute(select(analysis_runs).where(analysis_runs.c.id == analysis_run_id)).mappings().first()
            if run is None:
                return None
            reports = conn.execute(
                select(agent_reports)
                .where(agent_reports.c.analysis_run_id == analysis_run_id)
                .order_by(agent_reports.c.created_at, agent_reports.c.role)
            ).mappings().all()
            decision = conn.execute(
                select(trade_decisions).where(trade_decisions.c.analysis_run_id == analysis_run_id)
            ).mappings().first()
        return {
            "run": dict(run),
            "reports": [dict(report) for report in reports],
            "decision": dict(decision) if decision else None,
        }

    def list_public_analysis_runs(
        self,
        *,
        ticker_code: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List public analysis runs for feed/search pages."""

        if limit <= 0:
            raise ValueError("limit must be positive")

        stmt = (
            select(analysis_runs)
            .where(analysis_runs.c.visibility == "public")
            .order_by(desc(analysis_runs.c.trade_date), desc(analysis_runs.c.created_at))
            .limit(limit)
        )
        if ticker_code:
            stmt = stmt.where(analysis_runs.c.ticker_code == _normalize_ticker_code(ticker_code))

        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def latest_public_analysis_bundle(self, ticker_code: str) -> dict[str, Any] | None:
        """Return the newest public analysis bundle for a ticker."""

        runs = self.list_public_analysis_runs(ticker_code=ticker_code, limit=1)
        if not runs:
            return None
        return self.get_analysis_bundle(runs[0]["id"])

    def create_manual_portfolio(self, *, user_id: str, name: str, base_currency: str = "KRW") -> str:
        _validate_uuid(user_id, "portfolio user_id")
        portfolio_id = _id()
        with self.engine.begin() as conn:
            conn.execute(
                insert(manual_portfolios).values(
                    id=portfolio_id,
                    user_id=user_id,
                    name=name,
                    base_currency=base_currency,
                )
            )
        return portfolio_id

    def add_manual_trade(self, data: ManualTradeInput) -> str:
        _validate_manual_trade(data)
        ticker_name = data.ticker_name
        market = data.market
        if is_kr_ticker(data.ticker_code):
            resolved = resolve_kr_ticker(data.ticker_code, lookup_pykrx=False)
            ticker_name = ticker_name or resolved.name
            market = resolved.market

        trade_id = _id()
        values = {
            "id": trade_id,
            "portfolio_id": data.portfolio_id,
            "ticker_code": data.ticker_code.upper(),
            "ticker_name": ticker_name,
            "market": market,
            "side": data.side.lower(),
            "trade_date": data.trade_date,
            "price": data.price,
            "quantity": data.quantity,
            "fee": data.fee,
            "tax": data.tax,
            "memo": data.memo,
        }
        if data.created_at is not None:
            values["created_at"] = data.created_at
        with self.engine.begin() as conn:
            conn.execute(
                insert(manual_trades).values(**values)
            )
        return trade_id

    def set_price_target(
        self,
        *,
        portfolio_id: str,
        ticker_code: str,
        target_price: Decimal | None = None,
        stop_price: Decimal | None = None,
        memo: str | None = None,
    ) -> str:
        _validate_uuid(portfolio_id, "portfolio_id")
        normalized_ticker = _normalize_ticker_code(ticker_code)
        now = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(manual_price_targets.c.id).where(
                    manual_price_targets.c.portfolio_id == portfolio_id,
                    manual_price_targets.c.ticker_code == normalized_ticker,
                )
            ).scalar_one_or_none()
            if existing:
                conn.execute(
                    update(manual_price_targets)
                    .where(manual_price_targets.c.id == existing)
                    .values(
                        target_price=target_price,
                        stop_price=stop_price,
                        memo=memo,
                        updated_at=now,
                    )
                )
                return str(existing)

            target_id = _id()
            conn.execute(
                insert(manual_price_targets).values(
                    id=target_id,
                    portfolio_id=portfolio_id,
                    ticker_code=normalized_ticker,
                    target_price=target_price,
                    stop_price=stop_price,
                    memo=memo,
                    updated_at=now,
                )
            )
        return target_id

    def price_targets_for_portfolio(self, portfolio_id: str) -> list[dict[str, Any]]:
        _validate_uuid(portfolio_id, "portfolio_id")
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(manual_price_targets)
                .where(manual_price_targets.c.portfolio_id == portfolio_id)
                .order_by(manual_price_targets.c.ticker_code)
            ).mappings().all()
        return [dict(row) for row in rows]

    def manual_trades_for_portfolio(self, portfolio_id: str) -> list[dict[str, Any]]:
        _validate_uuid(portfolio_id, "portfolio_id")
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(manual_trades)
                .where(manual_trades.c.portfolio_id == portfolio_id)
                .order_by(manual_trades.c.trade_date, manual_trades.c.created_at)
            ).mappings().all()
        return [dict(row) for row in rows]

    def manual_positions(self, portfolio_id: str) -> dict[str, ManualPosition]:
        return calculate_manual_positions(self.manual_trades_for_portfolio(portfolio_id))


def _validate_visibility(value: str) -> None:
    if value not in {"public", "private"}:
        raise ValueError("visibility must be public or private")


def _validate_manual_trade(data: ManualTradeInput) -> None:
    _validate_uuid(data.portfolio_id, "portfolio_id")
    if data.side.lower() not in {"buy", "sell"}:
        raise ValueError("manual trade side must be buy or sell")
    if data.quantity <= 0:
        raise ValueError("manual trade quantity must be positive")
    if data.price <= 0:
        raise ValueError("manual trade price must be positive")
    if data.fee < 0 or data.tax < 0:
        raise ValueError("manual trade fee and tax cannot be negative")


def _validate_optional_uuid(value: str | None, field_name: str) -> None:
    if value is not None:
        _validate_uuid(value, field_name)


def _validate_uuid(value: str, field_name: str) -> None:
    try:
        UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a UUID string") from exc


def _normalize_ticker_code(value: str) -> str:
    if is_kr_ticker(value):
        return resolve_kr_ticker(value, lookup_pykrx=False).code
    return value.upper()


def _id() -> str:
    return str(uuid4())
