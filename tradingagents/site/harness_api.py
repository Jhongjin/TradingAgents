"""Payload builders and worker entry for the harness pipeline on the public site.

The web layer is read-only for the public and dry-run-only for operators: the
admin/cron endpoints may run the pipeline and persist decisions, but they
never pass ``--execute``. Real or 모의투자 orders stay in the operator CLI.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from tradingagents.storage import StorageRepository

from .public_api import _json_ready


HARNESS_NOTICES = [
    "하네스 결과는 스크리너·통계 예측·AI 토론·리스크 게이트를 거친 리서치 기록이며 매수 추천이나 투자 조언이 아닙니다.",
    "웹에서 실행되는 하네스는 항상 dry-run이며 실제 주문이나 브로커 주문과 연결되지 않습니다.",
]

STAGE_LABELS = {
    "screened": "스크리닝",
    "forecast_rejected": "예측 게이트 탈락",
    "confirmation_rejected": "AI 확인 탈락",
    "sized": "사이징",
    "gate_rejected": "만다트 게이트 탈락",
    "ordered": "가상 주문",
    "exit": "가상 청산",
}

SUPPORTED_WEB_CONFIRMERS = ("none", "playbook", "debate")


def build_harness_runs_payload(repo: StorageRepository | None, *, limit: int = 20, max_limit: int = 50) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > max_limit:
        raise ValueError(f"limit cannot exceed {max_limit}")
    if repo is None:
        return _json_ready({"status": "not_configured", "mode": "harness", "items": [], "notices": HARNESS_NOTICES})
    rows = repo.list_harness_runs(limit=limit)
    return _json_ready(
        {
            "status": "available" if rows else "empty",
            "mode": "harness",
            "execution_boundary": "dry_run_no_orders",
            "item_count": len(rows),
            "items": [_run_item(row) for row in rows],
            "notices": HARNESS_NOTICES,
        }
    )


def build_harness_run_payload(repo: StorageRepository | None, *, harness_run_id: str | None = None) -> dict[str, Any] | None:
    if repo is None:
        return _json_ready({"status": "not_configured", "mode": "harness", "notices": HARNESS_NOTICES})
    row = repo.get_harness_run(harness_run_id) if harness_run_id else repo.latest_harness_run()
    if row is None:
        return None
    decisions = [_decision_item(item) for item in row.get("decisions", [])]
    return _json_ready(
        {
            "status": "available",
            "mode": "harness",
            "execution_boundary": "dry_run_no_orders" if row.get("dry_run") else f"{row.get('broker')}_orders",
            "run": _run_item(row),
            "decisions": decisions,
            "summary": _summary(decisions),
            "notices": HARNESS_NOTICES,
        }
    )


def build_harness_ticker_history_payload(
    repo: StorageRepository | None,
    *,
    ticker_code: str,
    limit: int = 20,
) -> dict[str, Any]:
    if repo is None:
        return _json_ready({"status": "not_configured", "mode": "harness", "items": []})
    rows = repo.list_harness_decisions(ticker_code=ticker_code, limit=limit)
    return _json_ready(
        {
            "status": "available" if rows else "empty",
            "mode": "harness",
            "ticker_code": ticker_code,
            "item_count": len(rows),
            "items": [_decision_item(row) for row in rows],
            "notices": HARNESS_NOTICES,
        }
    )


def run_harness_for_web(
    repo: StorageRepository,
    *,
    confirmer: str = "none",
    confirm_top_n: int = 3,
    top_n: int = 20,
    markets: str = "KOSPI,KOSDAQ",
    as_of_date: str | None = None,
    llm_factory: Callable[[], Callable[[str], str]] | None = None,
) -> dict[str, Any]:
    """Run one dry-run pipeline cycle from the web worker and persist it.

    ``confirmer`` is limited to ``none``, ``playbook``, or ``debate``; the full
    tool-calling graph is too slow for serverless limits and belongs in the CLI.
    """

    from tradingagents.execution import AuditLedger
    from tradingagents.harness import PipelineConfig, run_daily_pipeline
    from tradingagents.harness.pipeline import debate_confirmer, playbook_confirmer
    from tradingagents.harness.tasks import llm_from_config
    from tradingagents.screener import ScreenerConfig

    selected = confirmer.strip().lower()
    if selected not in SUPPORTED_WEB_CONFIRMERS:
        raise ValueError(f"confirmer must be one of {', '.join(SUPPORTED_WEB_CONFIRMERS)}")
    market_tuple = tuple(part.strip().upper() for part in markets.split(",") if part.strip())
    config = PipelineConfig(
        markets=market_tuple,
        screener=ScreenerConfig(markets=market_tuple, top_n=top_n),
        confirm_top_n=confirm_top_n,
        dry_run=True,
        require_llm_confirmation=selected != "none",
    )
    chosen = None
    if selected != "none":
        llm = (llm_factory or llm_from_config)()
        chosen = playbook_confirmer(llm) if selected == "playbook" else debate_confirmer(llm)
    ledger = _web_ledger()
    result = run_daily_pipeline(
        as_of_date,
        config=config,
        confirmer=chosen,
        ledger=ledger,
        repo=repo,
        confirmer_name=selected,
    )
    payload = result.as_dict()
    payload["status"] = "processed"
    payload["mode"] = "harness"
    payload["inspect_path"] = f"/api/harness/runs/{result.run_id}" if result.run_id else "/api/harness/runs"
    payload["notices"] = HARNESS_NOTICES
    return _json_ready(payload)


def _web_ledger():
    from tradingagents.execution import AuditLedger

    path = os.getenv("TRADINGAGENTS_AUDIT_LOG_PATH")
    if not path:
        import tempfile

        path = os.path.join(tempfile.gettempdir(), "tradingagents", "harness-audit.jsonl")
    try:
        return AuditLedger(path)
    except OSError:
        return None


def _run_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "as_of_date": row.get("as_of_date"),
        "mode": row.get("mode"),
        "broker": row.get("broker"),
        "dry_run": bool(row.get("dry_run")),
        "confirmer": row.get("confirmer"),
        "status": row.get("status"),
        "markets": row.get("markets"),
        "universe_size": row.get("universe_size"),
        "candidate_count": row.get("candidate_count"),
        "order_count": row.get("order_count"),
        "cash_before": row.get("cash_before"),
        "cash_after": row.get("cash_after"),
        "notes": row.get("notes_json") or [],
        "metadata": row.get("metadata_json") or {},
        "created_at": row.get("created_at"),
        "detail_path": f"/harness/{row.get('id')}",
        "api_path": f"/api/harness/runs/{row.get('id')}",
    }


def _decision_item(row: dict[str, Any]) -> dict[str, Any]:
    stage = str(row.get("stage") or "")
    return {
        "id": str(row.get("id") or ""),
        "harness_run_id": str(row.get("harness_run_id") or ""),
        "as_of_date": row.get("as_of_date"),
        "ticker_code": row.get("ticker_code"),
        "ticker_name": row.get("ticker_name"),
        "market": row.get("market"),
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        "screener_rank": row.get("screener_rank"),
        "composite_score": row.get("composite_score"),
        "forecast_expected_return": row.get("forecast_expected_return"),
        "forecast_probability_up": row.get("forecast_probability_up"),
        "confirmation_rating": row.get("confirmation_rating"),
        "confirmation_confidence": row.get("confirmation_confidence"),
        "confirmation_source": row.get("confirmation_source"),
        "quantity": row.get("quantity"),
        "entry_price": row.get("entry_price"),
        "stop_price": row.get("stop_price"),
        "take_profit_price": row.get("take_profit_price"),
        "order_status": row.get("order_status"),
        "reasons": row.get("reasons_json") or [],
        "detail": row.get("detail_json") or {},
        "stock_path": f"/stocks/{row.get('ticker_code')}",
    }


def _summary(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in decisions:
        counts[item["stage"]] = counts.get(item["stage"], 0) + 1
    return {
        "decision_count": len(decisions),
        "stage_counts": counts,
        "ordered_count": counts.get("ordered", 0),
        "exit_count": counts.get("exit", 0),
        "rejected_count": sum(value for key, value in counts.items() if key.endswith("rejected")),
    }
