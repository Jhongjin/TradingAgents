"""Worker helpers for member-owned AI paper simulation records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from tradingagents.dataflows.chart_data import get_ohlcv_chart_series
from tradingagents.execution import PaperSimulationConfig, simulate_single_position
from tradingagents.storage import (
    PaperSimulationAccountInput,
    PaperSimulationEventInput,
    PaperSimulationPositionInput,
    StorageRepository,
)

from .simulation_api import _signal_from_decision


@dataclass(frozen=True)
class PaperSimulationWorkerResult:
    analysis_run_id: str
    ticker_code: str
    status: str
    user_id: str | None = None
    account_id: str | None = None
    position_id: str | None = None
    simulation_status: str | None = None
    realized_return: float | None = None
    unrealized_return: float | None = None
    error: str | None = None


def process_paper_simulations(
    repo: StorageRepository,
    *,
    limit: int = 20,
    as_of_date: str | date | None = None,
    chart_vendor: str | None = None,
    config: PaperSimulationConfig | None = None,
) -> list[PaperSimulationWorkerResult]:
    """Create new paper records and refresh open virtual positions."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    simulation_config = config or PaperSimulationConfig()
    results = process_open_paper_simulation_positions(
        repo,
        limit=limit,
        as_of_date=as_of_date,
        chart_vendor=chart_vendor,
        config=simulation_config,
    )
    remaining = max(limit - len(results), 0)
    if remaining:
        results.extend(
            process_paper_simulation_candidates(
                repo,
                limit=remaining,
                as_of_date=as_of_date,
                chart_vendor=chart_vendor,
                config=simulation_config,
            )
        )
    return results


def process_paper_simulation_candidates(
    repo: StorageRepository,
    *,
    limit: int = 20,
    as_of_date: str | date | None = None,
    chart_vendor: str | None = None,
    config: PaperSimulationConfig | None = None,
) -> list[PaperSimulationWorkerResult]:
    """Materialize completed member analyses into paper simulation records."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    results: list[PaperSimulationWorkerResult] = []
    for candidate in repo.list_paper_simulation_candidates(limit=limit):
        results.append(
            _process_candidate(
                repo,
                candidate,
                as_of_date=as_of_date,
                chart_vendor=chart_vendor,
                config=config or PaperSimulationConfig(),
            )
        )
    return results


def summarize_paper_simulation_results(results: Iterable[PaperSimulationWorkerResult]) -> dict[str, object]:
    rows = list(results)
    status_counts: dict[str, int] = {}
    returns = []
    for result in rows:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        if result.realized_return is not None:
            returns.append(float(result.realized_return))
    return {
        "result_count": len(rows),
        "status_counts": status_counts,
        "created_count": status_counts.get("created", 0),
        "updated_count": status_counts.get("updated", 0),
        "closed_count": status_counts.get("closed", 0),
        "still_open_count": status_counts.get("still_open", 0),
        "skipped_count": status_counts.get("skipped", 0),
        "unavailable_count": status_counts.get("unavailable", 0),
        "failed_count": status_counts.get("failed", 0),
        "average_realized_return": (sum(returns) / len(returns)) if returns else None,
    }


def process_open_paper_simulation_positions(
    repo: StorageRepository,
    *,
    limit: int = 20,
    as_of_date: str | date | None = None,
    chart_vendor: str | None = None,
    config: PaperSimulationConfig | None = None,
) -> list[PaperSimulationWorkerResult]:
    """Refresh open paper positions until they meet a virtual exit rule."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    simulation_config = config or PaperSimulationConfig()
    return [
        _process_open_position(
            repo,
            position,
            as_of_date=as_of_date,
            chart_vendor=chart_vendor,
            config=simulation_config,
        )
        for position in repo.list_open_paper_simulation_positions(limit=limit)
    ]


def _process_candidate(
    repo: StorageRepository,
    candidate: dict[str, Any],
    *,
    as_of_date: str | date | None,
    chart_vendor: str | None,
    config: PaperSimulationConfig,
) -> PaperSimulationWorkerResult:
    analysis_run_id = str(candidate.get("analysis_run_id") or "")
    ticker_code = str(candidate.get("ticker_code") or "")
    user_id = str(candidate.get("user_id") or "")
    if not analysis_run_id or not ticker_code or not user_id:
        return PaperSimulationWorkerResult(
            analysis_run_id=analysis_run_id,
            ticker_code=ticker_code,
            status="failed",
            user_id=user_id or None,
            error="missing_candidate_identity",
        )

    try:
        trade_date = _coerce_date(candidate.get("trade_date"))
        end_date = _coerce_date(as_of_date) if as_of_date is not None else datetime.now(ZoneInfo("Asia/Seoul")).date()
        if end_date < trade_date:
            return PaperSimulationWorkerResult(
                analysis_run_id=analysis_run_id,
                ticker_code=ticker_code,
                status="unavailable",
                user_id=user_id,
                error="as_of_date_before_trade_date",
            )

        series = get_ohlcv_chart_series(
            ticker_code,
            trade_date.isoformat(),
            end_date.isoformat(),
            vendor=chart_vendor or "pykrx",
        )
        if len(series.points) < 2:
            return PaperSimulationWorkerResult(
                analysis_run_id=analysis_run_id,
                ticker_code=ticker_code,
                status="unavailable",
                user_id=user_id,
                error="insufficient_price_data",
            )

        decision = {
            "rating": candidate.get("decision_rating"),
            "action": candidate.get("decision_action"),
            "target_weight": candidate.get("target_weight"),
            "rationale": candidate.get("rationale"),
            "raw_decision": candidate.get("raw_decision"),
        }
        simulation = simulate_single_position(
            _signal_from_decision(ticker_code, decision),
            [point.as_dict() for point in series.points],
            config=config,
        )
        if simulation.status == "skipped":
            return PaperSimulationWorkerResult(
                analysis_run_id=analysis_run_id,
                ticker_code=ticker_code,
                status="skipped",
                user_id=user_id,
                simulation_status=simulation.status,
                error=simulation.message,
            )

        account = repo.ensure_paper_simulation_account(
            PaperSimulationAccountInput(
                user_id=user_id,
                base_currency=config.currency.upper(),
                initial_cash=_money(config.initial_cash),
                metadata={"source": "paper_simulation_worker"},
            )
        )
        account_id = str(account["id"])
        position_id = repo.record_paper_simulation_position(
            _position_input(
                candidate,
                account_id=account_id,
                user_id=user_id,
                simulation=simulation.as_dict(),
                config=config,
                chart_vendor=series.vendor,
            )
        )
        for event in simulation.events:
            repo.add_paper_simulation_event(
                _event_input(
                    event,
                    account_id=account_id,
                    position_id=position_id,
                    user_id=user_id,
                    analysis_run_id=analysis_run_id,
                    ticker_code=ticker_code,
                )
            )
        return PaperSimulationWorkerResult(
            analysis_run_id=analysis_run_id,
            ticker_code=ticker_code,
            status="created",
            user_id=user_id,
            account_id=account_id,
            position_id=position_id,
            simulation_status=simulation.status,
            realized_return=simulation.trade_return,
            unrealized_return=simulation.unrealized_return,
        )
    except Exception as exc:
        return PaperSimulationWorkerResult(
            analysis_run_id=analysis_run_id,
            ticker_code=ticker_code,
            status="failed",
            user_id=user_id,
            error=f"{exc.__class__.__name__}: {exc}",
        )


def _process_open_position(
    repo: StorageRepository,
    position: dict[str, Any],
    *,
    as_of_date: str | date | None,
    chart_vendor: str | None,
    config: PaperSimulationConfig,
) -> PaperSimulationWorkerResult:
    position_id = str(position.get("id") or "")
    analysis_run_id = str(position.get("analysis_run_id") or "")
    ticker_code = str(position.get("ticker_code") or "")
    user_id = str(position.get("user_id") or "")
    account_id = str(position.get("account_id") or "")
    if not position_id or not analysis_run_id or not ticker_code or not user_id or not account_id:
        return PaperSimulationWorkerResult(
            analysis_run_id=analysis_run_id,
            ticker_code=ticker_code,
            status="failed",
            user_id=user_id or None,
            position_id=position_id or None,
            error="missing_open_position_identity",
        )

    try:
        entry_date = _coerce_date(position.get("entry_date"))
        end_date = _coerce_date(as_of_date) if as_of_date is not None else datetime.now(ZoneInfo("Asia/Seoul")).date()
        if end_date <= entry_date:
            return PaperSimulationWorkerResult(
                analysis_run_id=analysis_run_id,
                ticker_code=ticker_code,
                status="still_open",
                user_id=user_id,
                account_id=account_id,
                position_id=position_id,
                simulation_status="open",
                error="as_of_date_not_after_entry_date",
            )

        series = get_ohlcv_chart_series(
            ticker_code,
            entry_date.isoformat(),
            end_date.isoformat(),
            vendor=chart_vendor or "pykrx",
        )
        if len(series.points) < 2:
            return PaperSimulationWorkerResult(
                analysis_run_id=analysis_run_id,
                ticker_code=ticker_code,
                status="unavailable",
                user_id=user_id,
                account_id=account_id,
                position_id=position_id,
                error="insufficient_price_data",
            )

        decision = {
            "rating": position.get("decision_rating"),
            "action": position.get("decision_action"),
            "target_weight": position.get("target_weight"),
            "rationale": (position.get("metadata_json") or {}).get("rationale"),
        }
        simulation = simulate_single_position(
            _signal_from_decision(ticker_code, decision),
            [point.as_dict() for point in series.points],
            config=_config_for_position(position, config),
        )
        if simulation.status == "skipped":
            return PaperSimulationWorkerResult(
                analysis_run_id=analysis_run_id,
                ticker_code=ticker_code,
                status="skipped",
                user_id=user_id,
                account_id=account_id,
                position_id=position_id,
                simulation_status=simulation.status,
                error=simulation.message,
            )

        repo.record_paper_simulation_position(
            _position_input(
                position,
                account_id=account_id,
                user_id=user_id,
                simulation=simulation.as_dict(),
                config=_config_for_position(position, config),
                chart_vendor=series.vendor,
            )
        )
        if simulation.status == "closed":
            for event in simulation.events:
                if event.get("type") != "exit":
                    continue
                repo.add_paper_simulation_event(
                    _event_input(
                        event,
                        account_id=account_id,
                        position_id=position_id,
                        user_id=user_id,
                        analysis_run_id=analysis_run_id,
                        ticker_code=ticker_code,
                    )
                )
            return PaperSimulationWorkerResult(
                analysis_run_id=analysis_run_id,
                ticker_code=ticker_code,
                status="closed",
                user_id=user_id,
                account_id=account_id,
                position_id=position_id,
                simulation_status=simulation.status,
                realized_return=simulation.trade_return,
            )
        return PaperSimulationWorkerResult(
            analysis_run_id=analysis_run_id,
            ticker_code=ticker_code,
            status="still_open",
            user_id=user_id,
            account_id=account_id,
            position_id=position_id,
            simulation_status=simulation.status,
            unrealized_return=simulation.unrealized_return,
        )
    except Exception as exc:
        return PaperSimulationWorkerResult(
            analysis_run_id=analysis_run_id,
            ticker_code=ticker_code,
            status="failed",
            user_id=user_id,
            account_id=account_id or None,
            position_id=position_id or None,
            error=f"{exc.__class__.__name__}: {exc}",
        )


def _position_input(
    candidate: dict[str, Any],
    *,
    account_id: str,
    user_id: str,
    simulation: dict[str, Any],
    config: PaperSimulationConfig,
    chart_vendor: str,
) -> PaperSimulationPositionInput:
    events = simulation.get("events") or []
    entry = _event_by_type(events, "entry")
    exit_event = _event_by_type(events, "exit")
    entry_price = _money(entry.get("price")) if entry else None
    exit_price = _money(exit_event.get("price")) if exit_event else None
    realized_pnl = _realized_pnl(entry, exit_event)
    status = "closed" if simulation.get("status") == "closed" else "open"
    return PaperSimulationPositionInput(
        account_id=account_id,
        user_id=user_id,
        analysis_run_id=str(candidate.get("analysis_run_id") or "") or None,
        analysis_request_id=str(candidate.get("analysis_request_id") or "") or None,
        ticker_code=str(candidate.get("ticker_code") or ""),
        ticker_name=candidate.get("ticker_name"),
        market=str(candidate.get("market") or "KR"),
        status=status,
        quantity=int(entry.get("quantity") or 0) if entry else 0,
        entry_date=_optional_date(simulation.get("entry_date")),
        entry_price=entry_price,
        average_price=entry_price,
        target_price=_money(float(entry_price) * (1 + config.take_profit_pct)) if entry_price else None,
        stop_price=_money(float(entry_price) * (1 - config.stop_loss_pct)) if entry_price else None,
        exit_date=_optional_date(simulation.get("exit_date")),
        exit_price=exit_price,
        exit_reason=simulation.get("exit_reason"),
        realized_pnl=realized_pnl if status == "closed" else None,
        realized_return=simulation.get("trade_return"),
        decision_rating=candidate.get("decision_rating"),
        decision_action=candidate.get("decision_action"),
        target_weight=simulation.get("target_weight"),
        metadata={
            "source": "paper_simulation_worker",
            "chart_vendor": chart_vendor,
            "price_basis": "daily_close",
            "portfolio_return": simulation.get("portfolio_return"),
            "final_equity": simulation.get("final_equity"),
            "mark_date": simulation.get("mark_date"),
            "mark_price": simulation.get("mark_price"),
            "unrealized_return": simulation.get("unrealized_return"),
            "initial_cash": config.initial_cash,
            "max_position_weight": config.max_position_weight,
            "max_holding_days": config.max_holding_days,
            "take_profit_pct": config.take_profit_pct,
            "stop_loss_pct": config.stop_loss_pct,
            "slippage_bps": config.slippage_bps,
            "commission_per_trade": config.commission_per_trade,
            "currency": config.currency,
        },
    )


def _event_input(
    event: dict[str, Any],
    *,
    account_id: str,
    position_id: str,
    user_id: str,
    analysis_run_id: str,
    ticker_code: str,
) -> PaperSimulationEventInput:
    return PaperSimulationEventInput(
        account_id=account_id,
        position_id=position_id,
        user_id=user_id,
        analysis_run_id=analysis_run_id,
        event_type=str(event.get("type") or "note"),
        side=str(event.get("side") or "") or None,
        event_date=_coerce_date(event.get("date")),
        ticker_code=ticker_code,
        price=_optional_money(event.get("price")),
        quantity=int(event.get("quantity")) if event.get("quantity") is not None else None,
        notional=_optional_money(event.get("notional")),
        commission=_money(event.get("commission") or 0),
        transaction_tax=_money(event.get("transaction_tax") or 0),
        reason=event.get("reason"),
        metadata={"source": "paper_simulation_worker"},
    )


def _event_by_type(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("type") == event_type:
            return event
    return None


def _realized_pnl(entry: dict[str, Any] | None, exit_event: dict[str, Any] | None) -> Decimal | None:
    if entry is None or exit_event is None:
        return None
    entry_cost = _money(entry.get("notional") or 0) + _money(entry.get("commission") or 0) + _money(entry.get("transaction_tax") or 0)
    exit_value = _money(exit_event.get("notional") or 0) - _money(exit_event.get("commission") or 0) - _money(exit_event.get("transaction_tax") or 0)
    return exit_value - entry_cost


def _config_for_position(position: dict[str, Any], fallback: PaperSimulationConfig) -> PaperSimulationConfig:
    metadata = position.get("metadata_json") or {}
    return PaperSimulationConfig(
        initial_cash=float(metadata.get("initial_cash") or fallback.initial_cash),
        take_profit_pct=float(metadata.get("take_profit_pct") or fallback.take_profit_pct),
        stop_loss_pct=float(metadata.get("stop_loss_pct") or fallback.stop_loss_pct),
        max_holding_days=int(metadata.get("max_holding_days") or fallback.max_holding_days),
        max_position_weight=float(metadata.get("max_position_weight") or fallback.max_position_weight),
        slippage_bps=float(metadata.get("slippage_bps") or fallback.slippage_bps),
        commission_per_trade=float(metadata.get("commission_per_trade") or fallback.commission_per_trade),
        currency=str(metadata.get("currency") or fallback.currency),
    )


def _optional_money(value: Any) -> Decimal | None:
    if value is None:
        return None
    return _money(value)


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _optional_date(value: Any) -> date | None:
    if value is None:
        return None
    return _coerce_date(value)


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()
