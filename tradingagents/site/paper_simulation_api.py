"""Member-facing payloads for AI paper simulation records."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tradingagents.storage import StorageRepository

from .public_api import _json_ready


def build_member_paper_simulation_payload(
    repo: StorageRepository,
    *,
    user_id: str,
    limit: int = 20,
    max_limit: int = 50,
) -> dict[str, Any]:
    """Build a member-owned AI paper simulation summary."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > max_limit:
        raise ValueError(f"limit cannot exceed {max_limit}")

    account = repo.get_paper_simulation_account(user_id=user_id)
    if account is None:
        return _json_ready(
            {
                "status": "empty",
                "mode": "paper_simulation",
                "execution_boundary": "simulation_only_no_orders",
                "account": None,
                "summary": _summary([]),
                "positions": [],
                "events": [],
                "item_count": 0,
                "limit": limit,
                "notices": _notices(),
            }
        )

    positions = [_position_item(row) for row in repo.list_paper_simulation_positions(user_id=user_id, limit=limit)]
    events = [_event_item(row) for row in repo.list_paper_simulation_events(user_id=user_id, limit=limit)]
    return _json_ready(
        {
            "status": "available",
            "mode": "paper_simulation",
            "execution_boundary": "simulation_only_no_orders",
            "account": _account_item(account),
            "summary": _summary(positions),
            "positions": positions,
            "events": events,
            "item_count": len(positions),
            "limit": limit,
            "notices": _notices(),
        }
    )


def _account_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "name": row.get("name"),
        "base_currency": row.get("base_currency"),
        "initial_cash": row.get("initial_cash"),
        "cash_balance": row.get("cash_balance"),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _position_item(row: dict[str, Any]) -> dict[str, Any]:
    run_id = str(row.get("analysis_run_id") or "")
    code = str(row.get("ticker_code") or "")
    return {
        "id": str(row.get("id") or ""),
        "analysis_run_id": run_id or None,
        "analysis_request_id": str(row.get("analysis_request_id") or "") or None,
        "ticker_code": code,
        "ticker_name": row.get("ticker_name"),
        "market": row.get("market"),
        "status": row.get("status"),
        "quantity": row.get("quantity"),
        "entry_date": row.get("entry_date"),
        "entry_price": row.get("entry_price"),
        "average_price": row.get("average_price"),
        "target_price": row.get("target_price"),
        "stop_price": row.get("stop_price"),
        "exit_date": row.get("exit_date"),
        "exit_price": row.get("exit_price"),
        "exit_reason": row.get("exit_reason"),
        "realized_pnl": row.get("realized_pnl"),
        "realized_return": row.get("realized_return"),
        "decision_rating": row.get("decision_rating"),
        "decision_action": row.get("decision_action"),
        "target_weight": row.get("target_weight"),
        "metadata": row.get("metadata_json") or {},
        "report_path": f"/analyses/{run_id}" if run_id else None,
        "stock_path": f"/stocks/{code}" if code else None,
        "updated_at": row.get("updated_at"),
    }


def _event_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "position_id": str(row.get("position_id") or "") or None,
        "analysis_run_id": str(row.get("analysis_run_id") or "") or None,
        "event_type": row.get("event_type"),
        "side": row.get("side"),
        "event_date": row.get("event_date"),
        "ticker_code": row.get("ticker_code"),
        "price": row.get("price"),
        "quantity": row.get("quantity"),
        "notional": row.get("notional"),
        "commission": row.get("commission"),
        "transaction_tax": row.get("transaction_tax"),
        "reason": row.get("reason"),
        "metadata": row.get("metadata_json") or {},
    }


def _summary(positions: list[dict[str, Any]]) -> dict[str, Any]:
    open_count = sum(1 for position in positions if position.get("status") == "open")
    closed = [position for position in positions if position.get("status") == "closed"]
    wins = [position for position in closed if _decimal(position.get("realized_pnl")) > Decimal("0")]
    realized_pnl = sum((_decimal(position.get("realized_pnl")) for position in closed), Decimal("0"))
    unrealized_returns = [
        float((position.get("metadata") or {}).get("unrealized_return"))
        for position in positions
        if position.get("status") == "open" and (position.get("metadata") or {}).get("unrealized_return") is not None
    ]
    returns = [
        float(position["realized_return"])
        for position in closed
        if position.get("realized_return") is not None
    ]
    return {
        "open_count": open_count,
        "closed_count": len(closed),
        "win_count": len(wins),
        "loss_count": len(closed) - len(wins),
        "win_rate": (len(wins) / len(closed)) if closed else None,
        "total_realized_pnl": realized_pnl,
        "average_realized_return": (sum(returns) / len(returns)) if returns else None,
        "average_unrealized_return": (sum(unrealized_returns) / len(unrealized_returns)) if unrealized_returns else None,
        "latest_position_status": positions[0].get("status") if positions else None,
        "learning": _learning_summary(closed),
    }


def _learning_summary(closed_positions: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    for position in closed_positions:
        label = _learning_bucket_label(position)
        bucket = buckets.setdefault(
            label,
            {
                "label": label,
                "trade_count": 0,
                "win_count": 0,
                "loss_count": 0,
                "total_realized_pnl": Decimal("0"),
                "returns": [],
            },
        )
        realized_pnl = _decimal(position.get("realized_pnl"))
        realized_return = position.get("realized_return")
        bucket["trade_count"] += 1
        bucket["total_realized_pnl"] += realized_pnl
        if realized_pnl > Decimal("0"):
            bucket["win_count"] += 1
        else:
            bucket["loss_count"] += 1
        if realized_return is not None:
            bucket["returns"].append(float(realized_return))

    rows = []
    for bucket in buckets.values():
        trade_count = int(bucket["trade_count"])
        returns = bucket["returns"]
        rows.append(
            {
                "label": bucket["label"],
                "trade_count": trade_count,
                "win_count": int(bucket["win_count"]),
                "loss_count": int(bucket["loss_count"]),
                "win_rate": (int(bucket["win_count"]) / trade_count) if trade_count else None,
                "average_return": (sum(returns) / len(returns)) if returns else None,
                "total_realized_pnl": bucket["total_realized_pnl"],
            }
        )
    rows.sort(
        key=lambda item: (
            item.get("win_rate") if item.get("win_rate") is not None else -1,
            item.get("average_return") if item.get("average_return") is not None else -1,
            item.get("trade_count") or 0,
        ),
        reverse=True,
    )
    return {
        "closed_count": len(closed_positions),
        "bucket_count": len(rows),
        "best_bucket": rows[0] if rows else None,
        "buckets": rows[:6],
    }


def _learning_bucket_label(position: dict[str, Any]) -> str:
    metadata = position.get("metadata") or {}
    pattern_label = str(metadata.get("pattern_label") or "").strip()
    if pattern_label:
        return pattern_label
    decision = " / ".join(
        str(value).strip()
        for value in (position.get("decision_rating"), position.get("decision_action"))
        if str(value or "").strip()
    )
    return decision or "AI 의견"


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _notices() -> list[str]:
    return [
        "AI 모의투자 기록은 저장된 분석 리포트를 기준으로 계산한 기록입니다.",
        "실제 주문, 계좌 연결, 투자 자문 기능은 포함하지 않습니다.",
    ]
