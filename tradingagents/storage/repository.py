"""Repository layer for analysis runs and manual portfolios."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
from typing import Any
from uuid import UUID
from uuid import uuid4

from sqlalchemy import Engine, and_, create_engine, delete, desc, func, insert, select, text, update
from sqlalchemy.pool import StaticPool

from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker

from .models import (
    AgentReportInput,
    AnalysisOutcomeInput,
    AnalysisRequestInput,
    AnalysisRunInput,
    ManualTradeInput,
    PAPER_SIMULATION_ACCOUNT_NAME,
    PAPER_SIMULATION_LEGACY_ACCOUNT_NAME,
    PaperSimulationAccountInput,
    PaperSimulationEventInput,
    PaperSimulationPositionInput,
    TradeDecisionInput,
)
from .portfolio import ManualPosition, calculate_manual_positions
from .tables import (
    agent_reports,
    analysis_outcomes,
    analysis_refresh_requests,
    analysis_runs,
    manual_portfolios,
    manual_price_targets,
    manual_trades,
    manual_watchlist_items,
    manual_watchlists,
    metadata,
    paper_simulation_accounts,
    paper_simulation_events,
    paper_simulation_positions,
    trade_decisions,
)


POSTGRES_DRIVER_ENV = "TRADINGAGENTS_POSTGRES_DRIVER"
SUPPORTED_POSTGRES_DRIVERS = {"pg8000", "psycopg", "psycopg2"}


def create_storage_engine(database_url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine from DATABASE_URL or an in-memory SQLite DB."""

    url = database_url or os.getenv("DATABASE_URL") or "sqlite+pysqlite:///:memory:"
    url = _normalize_storage_url(url)
    if url == "sqlite+pysqlite:///:memory:":
        return create_engine(
            url,
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url, echo=echo, future=True)


def _normalize_storage_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", f"postgresql+{_postgres_driver()}://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", f"postgresql+{_postgres_driver()}://", 1)
    return url


def _postgres_driver() -> str:
    driver = os.getenv(POSTGRES_DRIVER_ENV, "pg8000").strip() or "pg8000"
    if driver not in SUPPORTED_POSTGRES_DRIVERS:
        raise ValueError(
            f"{POSTGRES_DRIVER_ENV} must be one of {', '.join(sorted(SUPPORTED_POSTGRES_DRIVERS))}"
        )
    return driver


class StorageRepository:
    """Small persistence facade used by future web/API layers."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def check_connection(self) -> None:
        """Open a lightweight connection to verify the configured storage is usable."""

        with self.engine.connect() as conn:
            conn.execute(text("select 1"))

    def check_schema(self) -> None:
        """Verify all application tables are present and queryable."""

        with self.engine.connect() as conn:
            for table in metadata.sorted_tables:
                conn.execute(select(table).limit(1))

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

    def upsert_analysis_outcome(self, data: AnalysisOutcomeInput) -> str:
        _validate_uuid(data.analysis_run_id, "analysis_run_id")
        _validate_analysis_outcome_status(data.status)
        if data.horizon_days <= 0:
            raise ValueError("horizon_days must be positive")
        if data.actual_holding_days is not None and data.actual_holding_days < 0:
            raise ValueError("actual_holding_days cannot be negative")

        values = {
            "analysis_run_id": data.analysis_run_id,
            "ticker_code": _normalize_ticker_code(data.ticker_code),
            "ticker_name": data.ticker_name,
            "market": data.market,
            "trade_date": data.trade_date,
            "evaluated_at": data.evaluated_at,
            "horizon_days": data.horizon_days,
            "actual_holding_days": data.actual_holding_days,
            "entry_close": data.entry_close,
            "exit_close": data.exit_close,
            "benchmark_symbol": data.benchmark_symbol,
            "benchmark_entry_close": data.benchmark_entry_close,
            "benchmark_exit_close": data.benchmark_exit_close,
            "raw_return": data.raw_return,
            "benchmark_return": data.benchmark_return,
            "alpha_return": data.alpha_return,
            "decision_rating": data.decision_rating,
            "decision_action": data.decision_action,
            "status": data.status,
            "error": data.error,
            "metadata_json": dict(data.metadata),
            "updated_at": datetime.now(timezone.utc),
        }
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(analysis_outcomes.c.id).where(
                    and_(
                        analysis_outcomes.c.analysis_run_id == data.analysis_run_id,
                        analysis_outcomes.c.horizon_days == data.horizon_days,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                conn.execute(update(analysis_outcomes).where(analysis_outcomes.c.id == existing).values(**values))
                return str(existing)

            outcome_id = _id()
            conn.execute(insert(analysis_outcomes).values(id=outcome_id, **values))
            return outcome_id

    def list_analysis_outcomes(
        self,
        *,
        analysis_run_id: str | None = None,
        ticker_code: str | None = None,
        status: str | None = None,
        limit: int = 20,
        public_only: bool = False,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        stmt = select(analysis_outcomes).order_by(
            desc(analysis_outcomes.c.trade_date),
            analysis_outcomes.c.horizon_days,
        ).limit(limit)
        if public_only:
            stmt = stmt.join(analysis_runs, analysis_outcomes.c.analysis_run_id == analysis_runs.c.id).where(
                analysis_runs.c.visibility == "public"
            )
        if analysis_run_id:
            _validate_uuid(analysis_run_id, "analysis_run_id")
            stmt = stmt.where(analysis_outcomes.c.analysis_run_id == analysis_run_id)
        if ticker_code:
            stmt = stmt.where(analysis_outcomes.c.ticker_code == _normalize_ticker_code(ticker_code))
        if status:
            _validate_analysis_outcome_status(status)
            stmt = stmt.where(analysis_outcomes.c.status == status)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

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
            outcomes = conn.execute(
                select(analysis_outcomes)
                .where(analysis_outcomes.c.analysis_run_id == analysis_run_id)
                .order_by(analysis_outcomes.c.horizon_days)
            ).mappings().all()
        return {
            "run": dict(run),
            "reports": [dict(report) for report in reports],
            "decision": dict(decision) if decision else None,
            "outcomes": [dict(outcome) for outcome in outcomes],
        }

    def list_public_analysis_runs(
        self,
        *,
        ticker_code: str | None = None,
        status: str | None = "completed",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List public analysis runs for feed/search pages."""

        if limit <= 0:
            raise ValueError("limit must be positive")

        stmt = self._public_analysis_runs_statement(ticker_code=ticker_code, status=status, limit=limit)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def _public_analysis_runs_statement(
        self,
        *,
        ticker_code: str | None = None,
        status: str | None = "completed",
        limit: int = 20,
    ):
        stmt = (
            select(analysis_runs)
            .where(analysis_runs.c.visibility == "public")
            .order_by(desc(analysis_runs.c.trade_date), desc(analysis_runs.c.created_at))
            .limit(limit)
        )
        if ticker_code:
            stmt = stmt.where(analysis_runs.c.ticker_code == _normalize_ticker_code(ticker_code))
        if status:
            stmt = stmt.where(analysis_runs.c.status == status)

        return stmt

    def list_public_analysis_feed_items(
        self,
        *,
        ticker_code: str | None = None,
        status: str | None = "completed",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List public feed rows with compact report, decision, and outcome summaries.

        This keeps the public feed from loading the full report bundle for every
        card while preserving the fields the API and HTML feed need.
        """

        if limit <= 0:
            raise ValueError("limit must be positive")

        run_stmt = self._public_analysis_runs_statement(ticker_code=ticker_code, status=status, limit=limit)
        with self.engine.begin() as conn:
            run_rows = conn.execute(run_stmt).mappings().all()
            if not run_rows:
                return []

            runs = [dict(row) for row in run_rows]
            run_ids = [str(run["id"]) for run in runs]
            report_count_rows = conn.execute(
                select(
                    agent_reports.c.analysis_run_id,
                    func.count(agent_reports.c.id).label("report_count"),
                )
                .where(agent_reports.c.analysis_run_id.in_(run_ids))
                .group_by(agent_reports.c.analysis_run_id)
            ).mappings().all()
            decision_rows = conn.execute(
                select(trade_decisions).where(trade_decisions.c.analysis_run_id.in_(run_ids))
            ).mappings().all()
            outcome_rows = conn.execute(
                select(analysis_outcomes)
                .where(
                    and_(
                        analysis_outcomes.c.analysis_run_id.in_(run_ids),
                        analysis_outcomes.c.status == "completed",
                    )
                )
                .order_by(analysis_outcomes.c.analysis_run_id, analysis_outcomes.c.horizon_days)
            ).mappings().all()

        report_counts = {
            str(row["analysis_run_id"]): int(row["report_count"] or 0)
            for row in report_count_rows
        }
        decisions = {str(row["analysis_run_id"]): dict(row) for row in decision_rows}
        completed_outcome_counts: dict[str, int] = {}
        preferred_outcomes: dict[str, dict[str, Any]] = {}
        for outcome in outcome_rows:
            run_id = str(outcome["analysis_run_id"])
            completed_outcome_counts[run_id] = completed_outcome_counts.get(run_id, 0) + 1
            preferred_outcomes.setdefault(run_id, dict(outcome))

        items: list[dict[str, Any]] = []
        for run in runs:
            item = dict(run)
            run_id = str(item["id"])
            decision = decisions.get(run_id)
            preferred_outcome = preferred_outcomes.get(run_id)
            item["report_path"] = f"/analyses/{run_id}"
            item["api_path"] = f"/api/analyses/{run_id}"
            item["report_count"] = report_counts.get(run_id, 0)
            item["completed_outcome_count"] = completed_outcome_counts.get(run_id, 0)
            if decision:
                item["decision_rating"] = decision.get("rating")
                item["decision_action"] = decision.get("action")
            if preferred_outcome:
                item["outcome_horizon_days"] = preferred_outcome.get("horizon_days")
                item["raw_return"] = preferred_outcome.get("raw_return")
                item["benchmark_return"] = preferred_outcome.get("benchmark_return")
                item["alpha_return"] = preferred_outcome.get("alpha_return")
            items.append(item)
        return items

    def latest_public_analysis_bundle(self, ticker_code: str) -> dict[str, Any] | None:
        """Return the newest public analysis bundle for a ticker."""

        runs = self.list_public_analysis_runs(ticker_code=ticker_code, limit=1)
        if not runs:
            return None
        return self.get_analysis_bundle(runs[0]["id"])

    def create_analysis_request(self, data: AnalysisRequestInput) -> str:
        _validate_optional_uuid(data.user_id, "analysis request user_id")
        _validate_analysis_request_status(data.status)
        ticker_code, ticker_name, market = _ticker_fields(data.ticker_code, data.ticker_name, data.market)
        request_id = _id()
        with self.engine.begin() as conn:
            conn.execute(
                insert(analysis_refresh_requests).values(
                    id=request_id,
                    user_id=data.user_id,
                    ticker_code=ticker_code,
                    ticker_name=ticker_name,
                    market=market,
                    requested_trade_date=data.requested_trade_date,
                    status=data.status,
                    reason=data.reason,
                    metadata_json=dict(data.metadata),
                )
            )
        return request_id

    def update_analysis_request_status(
        self,
        request_id: str,
        *,
        status: str,
        reason: str | None = None,
        analysis_run_id: str | None = None,
    ) -> None:
        _validate_uuid(request_id, "analysis_request_id")
        _validate_analysis_request_status(status)
        values: dict[str, Any] = {"status": status, "updated_at": datetime.now(timezone.utc)}
        with self.engine.begin() as conn:
            if reason is not None and status == "failed":
                row = (
                    conn.execute(
                        select(
                            analysis_refresh_requests.c.reason,
                            analysis_refresh_requests.c.metadata_json,
                        ).where(analysis_refresh_requests.c.id == request_id)
                    )
                    .mappings()
                    .first()
                )
                metadata = dict(row["metadata_json"] or {}) if row else {}
                if row and row["reason"]:
                    metadata.setdefault("request_reason", row["reason"])
                metadata["failure_reason"] = reason
                values["metadata_json"] = metadata
            elif reason is not None:
                values["reason"] = reason
            if analysis_run_id is not None:
                _validate_uuid(analysis_run_id, "analysis_run_id")
                values["analysis_run_id"] = analysis_run_id
            conn.execute(
                update(analysis_refresh_requests)
                .where(analysis_refresh_requests.c.id == request_id)
                .values(**values)
            )

    def list_analysis_requests(
        self,
        *,
        status: str | None = "queued",
        user_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if status is not None:
            _validate_analysis_request_status(status)
        _validate_optional_uuid(user_id, "analysis request user_id")

        stmt = (
            select(analysis_refresh_requests)
            .order_by(analysis_refresh_requests.c.created_at, analysis_refresh_requests.c.ticker_code)
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(analysis_refresh_requests.c.status == status)
        if user_id is not None:
            stmt = stmt.where(analysis_refresh_requests.c.user_id == user_id)

        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def get_analysis_request(self, request_id: str) -> dict[str, Any] | None:
        _validate_uuid(request_id, "analysis_request_id")
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    select(analysis_refresh_requests).where(analysis_refresh_requests.c.id == request_id)
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def find_active_analysis_request(
        self,
        *,
        user_id: str,
        ticker_code: str,
        requested_trade_date: Any,
        statuses: tuple[str, ...] = ("queued", "running"),
    ) -> dict[str, Any] | None:
        """Find an existing queued/running analysis request for de-duping."""

        _validate_uuid(user_id, "analysis request user_id")
        normalized_ticker = _normalize_ticker_code(ticker_code)
        for status in statuses:
            _validate_analysis_request_status(status)

        stmt = (
            select(analysis_refresh_requests)
            .where(
                analysis_refresh_requests.c.user_id == user_id,
                analysis_refresh_requests.c.ticker_code == normalized_ticker,
                analysis_refresh_requests.c.requested_trade_date == requested_trade_date,
                analysis_refresh_requests.c.status.in_(statuses),
            )
            .order_by(analysis_refresh_requests.c.created_at)
            .limit(1)
        )
        with self.engine.begin() as conn:
            row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None

    def count_analysis_requests(
        self,
        *,
        user_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
        created_at_from: datetime | None = None,
    ) -> int:
        """Count analysis refresh requests for quota and abuse controls."""

        _validate_optional_uuid(user_id, "analysis request user_id")
        if statuses is not None:
            if not statuses:
                return 0
            for status in statuses:
                _validate_analysis_request_status(status)

        stmt = select(func.count()).select_from(analysis_refresh_requests)
        if user_id is not None:
            stmt = stmt.where(analysis_refresh_requests.c.user_id == user_id)
        if statuses is not None:
            stmt = stmt.where(analysis_refresh_requests.c.status.in_(statuses))
        if created_at_from is not None:
            stmt = stmt.where(analysis_refresh_requests.c.created_at >= created_at_from)

        with self.engine.begin() as conn:
            count = conn.execute(stmt).scalar_one()
        return int(count)

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

    def get_manual_portfolio(self, portfolio_id: str) -> dict[str, Any] | None:
        _validate_uuid(portfolio_id, "portfolio_id")
        with self.engine.begin() as conn:
            row = conn.execute(
                select(manual_portfolios).where(manual_portfolios.c.id == portfolio_id)
            ).mappings().first()
        return dict(row) if row else None

    def list_manual_portfolios(self, *, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        _validate_uuid(user_id, "portfolio user_id")
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(manual_portfolios)
                .where(manual_portfolios.c.user_id == user_id)
                .order_by(desc(manual_portfolios.c.updated_at), desc(manual_portfolios.c.created_at))
                .limit(limit)
            ).mappings().all()
        return [dict(row) for row in rows]

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

    def create_watchlist(self, *, user_id: str, name: str) -> str:
        _validate_uuid(user_id, "watchlist user_id")
        watchlist_id = _id()
        with self.engine.begin() as conn:
            conn.execute(
                insert(manual_watchlists).values(
                    id=watchlist_id,
                    user_id=user_id,
                    name=name,
                )
            )
        return watchlist_id

    def get_watchlist(self, watchlist_id: str) -> dict[str, Any] | None:
        _validate_uuid(watchlist_id, "watchlist_id")
        with self.engine.begin() as conn:
            row = conn.execute(
                select(manual_watchlists).where(manual_watchlists.c.id == watchlist_id)
            ).mappings().first()
        return dict(row) if row else None

    def update_watchlist(self, *, watchlist_id: str, name: str) -> dict[str, Any] | None:
        _validate_uuid(watchlist_id, "watchlist_id")
        next_name = name.strip()
        if not next_name:
            raise ValueError("watchlist name cannot be empty")
        with self.engine.begin() as conn:
            conn.execute(
                update(manual_watchlists)
                .where(manual_watchlists.c.id == watchlist_id)
                .values(name=next_name, updated_at=datetime.now(timezone.utc))
            )
            row = conn.execute(
                select(manual_watchlists).where(manual_watchlists.c.id == watchlist_id)
            ).mappings().first()
        return dict(row) if row else None

    def list_watchlists(self, *, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        _validate_uuid(user_id, "watchlist user_id")
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(manual_watchlists)
                .where(manual_watchlists.c.user_id == user_id)
                .order_by(desc(manual_watchlists.c.updated_at), desc(manual_watchlists.c.created_at))
                .limit(limit)
            ).mappings().all()
        return [dict(row) for row in rows]

    def add_watchlist_item(
        self,
        *,
        watchlist_id: str,
        ticker_code: str,
        ticker_name: str | None = None,
        market: str = "KR",
        memo: str | None = None,
    ) -> str:
        _validate_uuid(watchlist_id, "watchlist_id")
        normalized_ticker = _normalize_ticker_code(ticker_code)
        if is_kr_ticker(ticker_code):
            resolved = resolve_kr_ticker(ticker_code, lookup_pykrx=False)
            ticker_name = ticker_name or resolved.name
            market = resolved.market
        now = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(manual_watchlist_items.c.id).where(
                    manual_watchlist_items.c.watchlist_id == watchlist_id,
                    manual_watchlist_items.c.ticker_code == normalized_ticker,
                )
            ).scalar_one_or_none()
            if existing:
                conn.execute(
                    update(manual_watchlist_items)
                    .where(manual_watchlist_items.c.id == existing)
                    .values(
                        ticker_name=ticker_name,
                        market=market,
                        memo=memo,
                        updated_at=now,
                    )
                )
                return str(existing)

            item_id = _id()
            conn.execute(
                insert(manual_watchlist_items).values(
                    id=item_id,
                    watchlist_id=watchlist_id,
                    ticker_code=normalized_ticker,
                    ticker_name=ticker_name,
                    market=market,
                    memo=memo,
                    updated_at=now,
                )
            )
        return item_id

    def remove_watchlist_item(self, *, watchlist_id: str, ticker_code: str) -> None:
        _validate_uuid(watchlist_id, "watchlist_id")
        normalized_ticker = _normalize_ticker_code(ticker_code)
        with self.engine.begin() as conn:
            conn.execute(
                delete(manual_watchlist_items).where(
                    manual_watchlist_items.c.watchlist_id == watchlist_id,
                    manual_watchlist_items.c.ticker_code == normalized_ticker,
                )
            )

    def watchlist_items(self, watchlist_id: str) -> list[dict[str, Any]]:
        _validate_uuid(watchlist_id, "watchlist_id")
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(manual_watchlist_items)
                .where(manual_watchlist_items.c.watchlist_id == watchlist_id)
                .order_by(manual_watchlist_items.c.created_at, manual_watchlist_items.c.ticker_code)
            ).mappings().all()
        return [dict(row) for row in rows]

    def get_paper_simulation_account(
        self,
        *,
        user_id: str,
        name: str = PAPER_SIMULATION_ACCOUNT_NAME,
    ) -> dict[str, Any] | None:
        _validate_uuid(user_id, "paper simulation user_id")
        names = [name]
        if name == PAPER_SIMULATION_ACCOUNT_NAME:
            names.append(PAPER_SIMULATION_LEGACY_ACCOUNT_NAME)
        with self.engine.begin() as conn:
            row = conn.execute(
                select(paper_simulation_accounts)
                .where(
                    paper_simulation_accounts.c.user_id == user_id,
                    paper_simulation_accounts.c.name.in_(names),
                )
                .order_by(desc(paper_simulation_accounts.c.name == name))
                .limit(1)
            ).mappings().first()
        return dict(row) if row else None

    def ensure_paper_simulation_account(self, data: PaperSimulationAccountInput) -> dict[str, Any]:
        _validate_paper_simulation_account(data)
        existing = self.get_paper_simulation_account(user_id=data.user_id, name=data.name)
        if existing:
            return existing

        account_id = _id()
        cash_balance = data.cash_balance if data.cash_balance is not None else data.initial_cash
        now = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            conn.execute(
                insert(paper_simulation_accounts).values(
                    id=account_id,
                    user_id=data.user_id,
                    name=data.name,
                    base_currency=data.base_currency,
                    initial_cash=data.initial_cash,
                    cash_balance=cash_balance,
                    status=data.status,
                    metadata_json=dict(data.metadata),
                    updated_at=now,
                )
            )
            row = conn.execute(
                select(paper_simulation_accounts).where(paper_simulation_accounts.c.id == account_id)
            ).mappings().one()
        return dict(row)

    def record_paper_simulation_position(self, data: PaperSimulationPositionInput) -> str:
        _validate_paper_simulation_position(data)
        ticker_code, ticker_name, market = _ticker_fields(data.ticker_code, data.ticker_name, data.market)
        values = {
            "account_id": data.account_id,
            "user_id": data.user_id,
            "analysis_run_id": data.analysis_run_id,
            "analysis_request_id": data.analysis_request_id,
            "ticker_code": ticker_code,
            "ticker_name": ticker_name,
            "market": market,
            "status": data.status,
            "quantity": data.quantity,
            "entry_date": data.entry_date,
            "entry_price": data.entry_price,
            "average_price": data.average_price,
            "target_price": data.target_price,
            "stop_price": data.stop_price,
            "exit_date": data.exit_date,
            "exit_price": data.exit_price,
            "exit_reason": data.exit_reason,
            "realized_pnl": data.realized_pnl,
            "realized_return": data.realized_return,
            "decision_rating": data.decision_rating,
            "decision_action": data.decision_action,
            "target_weight": data.target_weight,
            "metadata_json": dict(data.metadata),
            "updated_at": datetime.now(timezone.utc),
        }
        with self.engine.begin() as conn:
            existing = None
            if data.analysis_run_id is not None:
                existing = conn.execute(
                    select(paper_simulation_positions.c.id)
                    .where(
                        paper_simulation_positions.c.user_id == data.user_id,
                        paper_simulation_positions.c.analysis_run_id == data.analysis_run_id,
                    )
                    .limit(1)
                ).scalar_one_or_none()
            if existing:
                conn.execute(
                    update(paper_simulation_positions)
                    .where(paper_simulation_positions.c.id == existing)
                    .values(**values)
                )
                return str(existing)

            position_id = _id()
            conn.execute(insert(paper_simulation_positions).values(id=position_id, **values))
            return position_id

    def add_paper_simulation_event(self, data: PaperSimulationEventInput) -> str:
        _validate_paper_simulation_event(data)
        event_id = _id()
        with self.engine.begin() as conn:
            conn.execute(
                insert(paper_simulation_events).values(
                    id=event_id,
                    account_id=data.account_id,
                    position_id=data.position_id,
                    user_id=data.user_id,
                    analysis_run_id=data.analysis_run_id,
                    event_type=data.event_type,
                    side=data.side,
                    event_date=data.event_date,
                    ticker_code=_normalize_ticker_code(data.ticker_code),
                    price=data.price,
                    quantity=data.quantity,
                    notional=data.notional,
                    commission=data.commission,
                    transaction_tax=data.transaction_tax,
                    reason=data.reason,
                    metadata_json=dict(data.metadata),
                )
            )
        return event_id

    def list_paper_simulation_positions(
        self,
        *,
        user_id: str,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        _validate_uuid(user_id, "paper simulation user_id")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if status is not None:
            _validate_paper_position_status(status)
        stmt = (
            select(paper_simulation_positions)
            .where(paper_simulation_positions.c.user_id == user_id)
            .order_by(
                desc(paper_simulation_positions.c.updated_at),
                desc(paper_simulation_positions.c.created_at),
            )
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(paper_simulation_positions.c.status == status)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def list_open_paper_simulation_positions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        stmt = (
            select(paper_simulation_positions)
            .where(paper_simulation_positions.c.status == "open")
            .order_by(paper_simulation_positions.c.entry_date, paper_simulation_positions.c.created_at)
            .limit(limit)
        )
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def list_paper_simulation_events(
        self,
        *,
        user_id: str,
        position_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        _validate_uuid(user_id, "paper simulation user_id")
        if position_id is not None:
            _validate_uuid(position_id, "paper simulation position_id")
        if limit <= 0:
            raise ValueError("limit must be positive")
        stmt = (
            select(paper_simulation_events)
            .where(paper_simulation_events.c.user_id == user_id)
            .order_by(desc(paper_simulation_events.c.event_date), desc(paper_simulation_events.c.created_at))
            .limit(limit)
        )
        if position_id is not None:
            stmt = stmt.where(paper_simulation_events.c.position_id == position_id)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def count_paper_simulation_positions(
        self,
        *,
        user_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> int:
        _validate_optional_uuid(user_id, "paper simulation user_id")
        if statuses is not None:
            if not statuses:
                return 0
            for status in statuses:
                _validate_paper_position_status(status)
        stmt = select(func.count()).select_from(paper_simulation_positions)
        if user_id is not None:
            stmt = stmt.where(paper_simulation_positions.c.user_id == user_id)
        if statuses is not None:
            stmt = stmt.where(paper_simulation_positions.c.status.in_(statuses))
        with self.engine.begin() as conn:
            count = conn.execute(stmt).scalar_one()
        return int(count)

    def list_paper_simulation_learning_positions(
        self,
        *,
        ticker_code: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return closed paper positions for anonymous aggregate learning."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        normalized_ticker = _normalize_ticker_code(ticker_code) if ticker_code else None
        stmt = (
            select(
                paper_simulation_positions.c.ticker_code,
                paper_simulation_positions.c.ticker_name,
                paper_simulation_positions.c.market,
                paper_simulation_positions.c.status,
                paper_simulation_positions.c.entry_date,
                paper_simulation_positions.c.entry_price,
                paper_simulation_positions.c.exit_date,
                paper_simulation_positions.c.exit_price,
                paper_simulation_positions.c.exit_reason,
                paper_simulation_positions.c.realized_pnl,
                paper_simulation_positions.c.realized_return,
                paper_simulation_positions.c.decision_rating,
                paper_simulation_positions.c.decision_action,
                paper_simulation_positions.c.target_weight,
                paper_simulation_positions.c.metadata_json,
                paper_simulation_positions.c.updated_at,
            )
            .where(paper_simulation_positions.c.status == "closed")
            .order_by(desc(paper_simulation_positions.c.updated_at), desc(paper_simulation_positions.c.created_at))
            .limit(limit)
        )
        if normalized_ticker:
            stmt = stmt.where(paper_simulation_positions.c.ticker_code == normalized_ticker)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def list_paper_simulation_candidates(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """List completed member analyses that do not yet have a paper position."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        effective_user_id = func.coalesce(
            analysis_runs.c.user_id,
            analysis_refresh_requests.c.user_id,
        )
        stmt = (
            select(
                analysis_runs.c.id.label("analysis_run_id"),
                analysis_runs.c.user_id.label("run_user_id"),
                analysis_refresh_requests.c.id.label("analysis_request_id"),
                analysis_refresh_requests.c.user_id.label("request_user_id"),
                effective_user_id.label("user_id"),
                analysis_runs.c.ticker_code,
                analysis_runs.c.ticker_name,
                analysis_runs.c.market,
                analysis_runs.c.trade_date,
                analysis_runs.c.visibility,
                analysis_runs.c.status,
                trade_decisions.c.rating.label("decision_rating"),
                trade_decisions.c.action.label("decision_action"),
                trade_decisions.c.target_weight,
                trade_decisions.c.rationale,
                trade_decisions.c.raw_decision,
            )
            .select_from(
                analysis_runs
                .join(trade_decisions, trade_decisions.c.analysis_run_id == analysis_runs.c.id)
                .outerjoin(analysis_refresh_requests, analysis_refresh_requests.c.analysis_run_id == analysis_runs.c.id)
                .outerjoin(
                    paper_simulation_positions,
                    paper_simulation_positions.c.analysis_run_id == analysis_runs.c.id,
                )
            )
            .where(
                analysis_runs.c.status == "completed",
                paper_simulation_positions.c.id.is_(None),
                effective_user_id.is_not(None),
            )
            .order_by(desc(analysis_runs.c.completed_at), desc(analysis_runs.c.created_at))
            .limit(limit)
        )
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]


def _validate_visibility(value: str) -> None:
    if value not in {"public", "private"}:
        raise ValueError("visibility must be public or private")


def _validate_analysis_request_status(value: str) -> None:
    if value not in {"queued", "running", "completed", "failed", "skipped"}:
        raise ValueError("analysis request status is invalid")


def _validate_analysis_outcome_status(value: str) -> None:
    if value not in {"pending", "completed", "unavailable"}:
        raise ValueError("analysis outcome status is invalid")


def _validate_paper_account_status(value: str) -> None:
    if value not in {"active", "paused", "archived"}:
        raise ValueError("paper simulation account status is invalid")


def _validate_paper_position_status(value: str) -> None:
    if value not in {"open", "closed"}:
        raise ValueError("paper simulation position status is invalid")


def _validate_paper_event_type(value: str) -> None:
    if value not in {"entry", "exit", "note"}:
        raise ValueError("paper simulation event type is invalid")


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


def _validate_paper_simulation_account(data: PaperSimulationAccountInput) -> None:
    _validate_uuid(data.user_id, "paper simulation user_id")
    _validate_paper_account_status(data.status)
    if not data.name.strip():
        raise ValueError("paper simulation account name cannot be empty")
    if data.base_currency.upper() != data.base_currency or len(data.base_currency) > 8:
        raise ValueError("paper simulation base_currency must be uppercase")
    if data.initial_cash <= 0:
        raise ValueError("paper simulation initial_cash must be positive")
    if data.cash_balance is not None and data.cash_balance < 0:
        raise ValueError("paper simulation cash_balance cannot be negative")


def _validate_paper_simulation_position(data: PaperSimulationPositionInput) -> None:
    _validate_uuid(data.account_id, "paper simulation account_id")
    _validate_uuid(data.user_id, "paper simulation user_id")
    _validate_optional_uuid(data.analysis_run_id, "paper simulation analysis_run_id")
    _validate_optional_uuid(data.analysis_request_id, "paper simulation analysis_request_id")
    _validate_paper_position_status(data.status)
    if data.quantity < 0:
        raise ValueError("paper simulation quantity cannot be negative")
    for field_name in ("entry_price", "average_price", "target_price", "stop_price", "exit_price"):
        value = getattr(data, field_name)
        if value is not None and value <= 0:
            raise ValueError(f"paper simulation {field_name} must be positive")
    if data.realized_pnl is not None and data.status != "closed":
        raise ValueError("paper simulation realized_pnl requires a closed position")


def _validate_paper_simulation_event(data: PaperSimulationEventInput) -> None:
    _validate_uuid(data.account_id, "paper simulation account_id")
    _validate_uuid(data.user_id, "paper simulation user_id")
    _validate_optional_uuid(data.position_id, "paper simulation position_id")
    _validate_optional_uuid(data.analysis_run_id, "paper simulation analysis_run_id")
    _validate_paper_event_type(data.event_type)
    if data.side is not None and data.side not in {"buy", "sell"}:
        raise ValueError("paper simulation event side must be buy or sell")
    if data.quantity is not None and data.quantity <= 0:
        raise ValueError("paper simulation event quantity must be positive")
    for field_name in ("price", "notional"):
        value = getattr(data, field_name)
        if value is not None and value <= 0:
            raise ValueError(f"paper simulation event {field_name} must be positive")
    if data.commission < 0 or data.transaction_tax < 0:
        raise ValueError("paper simulation event costs cannot be negative")


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


def _ticker_fields(ticker_code: str, ticker_name: str | None, market: str) -> tuple[str, str | None, str]:
    if is_kr_ticker(ticker_code):
        resolved = resolve_kr_ticker(ticker_code, lookup_pykrx=False)
        return resolved.code, ticker_name or resolved.name, resolved.market
    return ticker_code.upper(), ticker_name, market


def _id() -> str:
    return str(uuid4())
