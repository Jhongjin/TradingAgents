"""Worker helpers for member-owned AI paper simulation records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable, Mapping
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
            (trade_date - timedelta(days=90)).isoformat(),
            end_date.isoformat(),
            vendor=chart_vendor or "pykrx",
        )
        price_points = [point.as_dict() for point in series.points]
        simulation_points = _points_on_or_after(price_points, trade_date)
        if len(simulation_points) < 2:
            return PaperSimulationWorkerResult(
                analysis_run_id=analysis_run_id,
                ticker_code=ticker_code,
                status="unavailable",
                user_id=user_id,
                error="insufficient_price_data",
            )
        entry_pattern = _entry_pattern_metadata(price_points, trade_date)

        decision = {
            "rating": candidate.get("decision_rating"),
            "action": candidate.get("decision_action"),
            "target_weight": candidate.get("target_weight"),
            "rationale": candidate.get("rationale"),
            "raw_decision": candidate.get("raw_decision"),
        }
        simulation = simulate_single_position(
            _signal_from_decision(ticker_code, decision),
            simulation_points,
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
        position_input = _position_input(
            candidate,
            account_id=account_id,
            user_id=user_id,
            simulation=simulation.as_dict(),
            config=config,
            chart_vendor=series.vendor,
            entry_pattern=entry_pattern,
        )
        position_id = repo.record_paper_simulation_position(position_input)
        for event in simulation.events:
            repo.add_paper_simulation_event(
                _event_input(
                    event,
                    account_id=account_id,
                    position_id=position_id,
                    user_id=user_id,
                    analysis_run_id=analysis_run_id,
                    ticker_code=ticker_code,
                    position_metadata=position_input.metadata,
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

        position_input = _position_input(
            position,
            account_id=account_id,
            user_id=user_id,
            simulation=simulation.as_dict(),
            config=_config_for_position(position, config),
            chart_vendor=series.vendor,
        )
        repo.record_paper_simulation_position(position_input)
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
                        position_metadata=position_input.metadata,
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
    entry_pattern: dict[str, Any] | None = None,
) -> PaperSimulationPositionInput:
    events = simulation.get("events") or []
    entry = _event_by_type(events, "entry")
    exit_event = _event_by_type(events, "exit")
    entry_price = _money(entry.get("price")) if entry else None
    exit_price = _money(exit_event.get("price")) if exit_event else None
    realized_pnl = _realized_pnl(entry, exit_event)
    status = "closed" if simulation.get("status") == "closed" else "open"
    metadata = _position_metadata(
        candidate,
        simulation=simulation,
        config=config,
        chart_vendor=chart_vendor,
        entry_pattern=entry_pattern,
    )
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
        metadata=metadata,
    )


def _position_metadata(
    candidate: dict[str, Any],
    *,
    simulation: dict[str, Any],
    config: PaperSimulationConfig,
    chart_vendor: str,
    entry_pattern: dict[str, Any] | None,
) -> dict[str, Any]:
    existing = candidate.get("metadata_json") if isinstance(candidate.get("metadata_json"), dict) else {}
    metadata = {
        **existing,
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
    }
    if entry_pattern:
        metadata["entry_pattern"] = entry_pattern
        label = str(entry_pattern.get("label") or "").strip()
        if label:
            metadata["pattern_label"] = label
    metadata["entry_reason"] = _entry_reason_metadata(candidate, entry_pattern=entry_pattern, config=config)
    if simulation.get("status") == "closed":
        metadata["exit_reason_detail"] = _exit_reason_metadata(simulation, config=config)
    metadata["post_trade_evaluation"] = _post_trade_evaluation(simulation, config=config, entry_pattern=entry_pattern)
    return metadata


def _entry_reason_metadata(
    candidate: dict[str, Any],
    *,
    entry_pattern: dict[str, Any] | None,
    config: PaperSimulationConfig,
) -> dict[str, Any]:
    rating = str(candidate.get("decision_rating") or "").strip()
    action = str(candidate.get("decision_action") or "").strip()
    target_weight = candidate.get("target_weight")
    pattern_label = str((entry_pattern or {}).get("label") or "").strip()
    decision = " / ".join(part for part in (rating, action) if part) or "AI 의견"
    weight_text = f"{float(target_weight) * 100:.1f}%" if target_weight is not None else f"최대 {config.max_position_weight * 100:.0f}%"
    summary = f"{decision} 의견을 기준으로 {weight_text} 한도에서 가상 진입했습니다."
    detail = (
        f"진입 패턴은 {pattern_label}입니다. "
        "이 기록은 분석 요청 결과를 복기하기 위한 가상 체결이며 실제 주문과 연결되지 않습니다."
        if pattern_label
        else "가격 이력이 부족해 패턴 라벨은 보수적으로 비워두고, 분석 요청 결과만 기준으로 가상 진입했습니다."
    )
    return {
        "decision": decision,
        "target_weight": target_weight,
        "pattern_label": pattern_label or None,
        "summary": summary,
        "detail": detail,
        "execution_boundary": "simulation_only_no_orders",
    }


def _exit_reason_metadata(simulation: dict[str, Any], *, config: PaperSimulationConfig) -> dict[str, Any]:
    reason = str(simulation.get("exit_reason") or "")
    trade_return = simulation.get("trade_return")
    holding_days = int(simulation.get("holding_days") or 0)
    labels = {
        "take_profit": "익절 기준 도달",
        "stop_loss": "손절 기준 도달",
        "max_holding_days": "보유 기간 종료",
    }
    thresholds = {
        "take_profit": config.take_profit_pct,
        "stop_loss": -config.stop_loss_pct,
        "max_holding_days": config.max_holding_days,
    }
    if reason == "take_profit":
        detail = f"종가 기준 수익률이 +{config.take_profit_pct * 100:.1f}% 익절선을 넘어서 가상 청산했습니다."
    elif reason == "stop_loss":
        detail = f"종가 기준 수익률이 -{config.stop_loss_pct * 100:.1f}% 손절선을 지나 가상 청산했습니다."
    elif reason == "max_holding_days":
        detail = f"{config.max_holding_days}거래일 보유 한도에 도달해 결과를 확정했습니다."
    else:
        detail = "가상 청산 기준을 확인한 뒤 결과를 확정했습니다."
    return {
        "reason": reason or None,
        "label": labels.get(reason, reason or "청산 기준"),
        "threshold": thresholds.get(reason),
        "holding_days": holding_days,
        "trade_return": trade_return,
        "summary": f"{labels.get(reason, reason or '청산 기준')} · {holding_days}거래일 · {_signed_percent_text(trade_return)}",
        "detail": detail,
    }


def _post_trade_evaluation(
    simulation: dict[str, Any],
    *,
    config: PaperSimulationConfig,
    entry_pattern: dict[str, Any] | None,
) -> dict[str, Any]:
    status = str(simulation.get("status") or "")
    trade_return = simulation.get("trade_return")
    unrealized_return = simulation.get("unrealized_return")
    exit_reason = str(simulation.get("exit_reason") or "")
    active_return = trade_return if status == "closed" else unrealized_return
    if status == "open":
        outcome = _open_outcome_label(unrealized_return)
        summary = f"가상 보유 중 · 최근 평가 {_signed_percent_text(unrealized_return)}"
    else:
        outcome = _closed_outcome_label(exit_reason=exit_reason, trade_return=trade_return)
        summary = f"{outcome} · 실현 수익률 {_signed_percent_text(trade_return)}"
    notes = _evaluation_notes(
        status=status,
        exit_reason=exit_reason,
        return_value=active_return,
        entry_pattern=entry_pattern,
        config=config,
    )
    return {
        "status": status,
        "outcome_label": outcome,
        "summary": summary,
        "holding_days": simulation.get("holding_days"),
        "realized_return": trade_return,
        "unrealized_return": unrealized_return,
        "portfolio_return": simulation.get("portfolio_return"),
        "mark_date": simulation.get("mark_date"),
        "mark_price": simulation.get("mark_price"),
        "exit_reason": exit_reason or None,
        "notes": notes,
        "execution_boundary": "simulation_only_no_orders",
    }


def _closed_outcome_label(*, exit_reason: str, trade_return: Any) -> str:
    value = _float_or_none(trade_return)
    if exit_reason == "take_profit":
        return "목표 달성"
    if exit_reason == "stop_loss":
        return "위험 차단"
    if value is None:
        return "기간 종료"
    if value > 0:
        return "기간 종료 수익"
    if value < 0:
        return "기간 종료 손실"
    return "기간 종료 보합"


def _open_outcome_label(unrealized_return: Any) -> str:
    value = _float_or_none(unrealized_return)
    if value is None:
        return "보유 평가 대기"
    if value >= 0:
        return "보유 평가 수익"
    return "보유 평가 손실"


def _evaluation_notes(
    *,
    status: str,
    exit_reason: str,
    return_value: Any,
    entry_pattern: dict[str, Any] | None,
    config: PaperSimulationConfig,
) -> list[str]:
    notes = ["실제 주문 없이 분석 요청 결과를 사후 복기하기 위한 가상 기록입니다."]
    pattern_label = str((entry_pattern or {}).get("label") or "").strip()
    if pattern_label:
        notes.append(f"진입 시점 패턴: {pattern_label}.")
    if status == "open":
        notes.append(f"익절 +{config.take_profit_pct * 100:.1f}%, 손절 -{config.stop_loss_pct * 100:.1f}% 기준으로 계속 관찰합니다.")
    elif exit_reason == "take_profit":
        notes.append("익절 기준에 먼저 닿아 AI 진입 가정이 우호적으로 검증됐습니다.")
    elif exit_reason == "stop_loss":
        notes.append("손절 기준이 먼저 작동해 다음 분석에서 리스크 요인을 더 강하게 반영해야 합니다.")
    elif exit_reason == "max_holding_days":
        notes.append(f"{config.max_holding_days}거래일 안에 익절/손절 기준이 나오지 않아 기간 기준으로 평가했습니다.")
    value = _float_or_none(return_value)
    if value is not None:
        notes.append(f"가격 기준 수익률: {_signed_percent_text(value)}.")
    return notes


def _signed_percent_text(value: Any) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "-"
    return f"{parsed * 100:+.2f}%"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _points_on_or_after(points: list[dict[str, Any]], start_date: date) -> list[dict[str, Any]]:
    return [
        point
        for point in points
        if point.get("close") is not None and _coerce_date(point.get("date")) >= start_date
    ]


def _entry_pattern_metadata(points: list[dict[str, Any]], entry_date: date) -> dict[str, Any]:
    history = [
        point
        for point in points
        if point.get("close") is not None and _coerce_date(point.get("date")) <= entry_date
    ]
    if len(history) < 20:
        return {"status": "insufficient_history", "lookback_points": len(history)}

    closes = [float(point["close"]) for point in history]
    volumes = [
        float(point.get("volume") or 0)
        for point in history
        if point.get("volume") is not None
    ]
    entry_close = closes[-1]
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    ma60 = (sum(closes[-60:]) / 60) if len(closes) >= 60 else None
    return_5d = (entry_close / closes[-6] - 1) if len(closes) >= 6 and closes[-6] else None
    avg_volume20 = (sum(volumes[-20:]) / 20) if len(volumes) >= 20 else None
    entry_volume = volumes[-1] if volumes else None

    trend = _trend_state(entry_close=entry_close, ma5=ma5, ma20=ma20, ma60=ma60)
    momentum = _momentum_state(return_5d)
    volume = _volume_state(entry_volume=entry_volume, average_volume=avg_volume20)
    label = _pattern_label(trend=trend, momentum=momentum, volume=volume)
    return {
        "status": "available",
        "label": label,
        "trend": trend,
        "momentum": momentum,
        "volume": volume,
        "entry_close": entry_close,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "return_5d": return_5d,
        "volume_ratio": (entry_volume / avg_volume20) if entry_volume and avg_volume20 else None,
        "lookback_points": len(history),
    }


def _trend_state(*, entry_close: float, ma5: float, ma20: float, ma60: float | None) -> str:
    if ma60 is not None and entry_close >= ma5 >= ma20 >= ma60:
        return "stacked_uptrend"
    if entry_close >= ma20 and ma5 >= ma20:
        return "above_ma20"
    if entry_close < ma20 and ma5 < ma20:
        return "below_ma20"
    return "mixed"


def _momentum_state(return_5d: float | None) -> str:
    if return_5d is None:
        return "unknown"
    if return_5d >= 0.05:
        return "short_momentum"
    if return_5d <= -0.05:
        return "pullback"
    return "range"


def _volume_state(*, entry_volume: float | None, average_volume: float | None) -> str:
    if not entry_volume or not average_volume:
        return "unknown"
    ratio = entry_volume / average_volume
    if ratio >= 1.5:
        return "volume_spike"
    if ratio <= 0.7:
        return "thin_volume"
    return "normal_volume"


def _pattern_label(*, trend: str, momentum: str, volume: str) -> str:
    trend_labels = {
        "stacked_uptrend": "정배열 상승추세",
        "above_ma20": "20일선 위",
        "below_ma20": "20일선 아래",
        "mixed": "혼조 구간",
    }
    momentum_labels = {
        "short_momentum": "단기 강세",
        "pullback": "단기 약세",
        "range": "횡보",
        "unknown": "모멘텀 부족",
    }
    label = f"{trend_labels.get(trend, '혼조 구간')} / {momentum_labels.get(momentum, '확인 필요')}"
    if volume == "volume_spike":
        return f"{label} / 거래량 증가"
    if volume == "thin_volume":
        return f"{label} / 거래량 감소"
    return label


def _event_input(
    event: dict[str, Any],
    *,
    account_id: str,
    position_id: str,
    user_id: str,
    analysis_run_id: str,
    ticker_code: str,
    position_metadata: Mapping[str, Any] | None = None,
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
        metadata=_event_metadata(event, position_metadata=position_metadata),
    )


def _event_metadata(event: dict[str, Any], *, position_metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    metadata = {"source": "paper_simulation_worker"}
    position_metadata = position_metadata or {}
    event_type = str(event.get("type") or "")
    if event_type == "entry":
        entry_reason = position_metadata.get("entry_reason")
        if isinstance(entry_reason, Mapping):
            metadata["reason_label"] = "AI 분석 진입"
            metadata["reason_summary"] = entry_reason.get("summary")
            metadata["reason_detail"] = entry_reason.get("detail")
    elif event_type == "exit":
        exit_reason = position_metadata.get("exit_reason_detail")
        evaluation = position_metadata.get("post_trade_evaluation")
        if isinstance(exit_reason, Mapping):
            metadata["reason_label"] = exit_reason.get("label")
            metadata["reason_summary"] = exit_reason.get("summary")
            metadata["reason_detail"] = exit_reason.get("detail")
        if isinstance(evaluation, Mapping):
            metadata["evaluation_summary"] = evaluation.get("summary")
            metadata["outcome_label"] = evaluation.get("outcome_label")
    return {key: value for key, value in metadata.items() if value is not None}


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
