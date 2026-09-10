"""What rules the account is run under, and when they changed.

Every run stores the configuration it used, so the current rules and their
history can be read back from the runs themselves. Publishing that matters:
a track record built under one stop-loss is not comparable to one built under
another, and a reader cannot judge the record without knowing which is which.
"""

from __future__ import annotations

from typing import Any, Mapping

RULE_LABELS: tuple[tuple[str, str, str], ...] = (
    ("take_profit_pct", "목표가", "매수가 대비"),
    ("stop_loss_pct", "손절가", "매수가 대비"),
    ("max_holding_days", "최대 보유", "거래일"),
    ("max_position_weight", "종목당 비중 상한", "자산 대비"),
    ("min_cash_reserve_pct", "현금 최소 보유", "자산 대비"),
    ("risk_percent_per_trade", "거래당 위험 예산", "자산 대비"),
    ("min_probability_up", "상승 확률 하한", "예측 기준"),
    ("min_expected_return", "기대 수익률 하한", "예측 기준"),
    ("min_confidence", "AI 확신도 하한", "판정 기준"),
    ("confirm_top_n", "AI 확인 종목 수", "후보 중"),
)

PERCENT_KEYS = {
    "take_profit_pct",
    "stop_loss_pct",
    "max_position_weight",
    "min_cash_reserve_pct",
    "risk_percent_per_trade",
    "min_probability_up",
    "min_expected_return",
    "min_confidence",
}


def format_rule(key: str, value: Any) -> str:
    if value is None:
        return "-"
    if key in PERCENT_KEYS:
        try:
            return f"{float(value) * 100:g}%"
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _run_config(run: Mapping[str, Any]) -> dict[str, Any]:
    metadata = run.get("metadata") or run.get("metadata_json") or {}
    config = metadata.get("config") if isinstance(metadata, Mapping) else None
    return dict(config) if isinstance(config, Mapping) else {}


def build_rules_payload(runs: list[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Current rules plus the days a value changed, newest first."""

    ordered = [run for run in (runs or []) if _run_config(run)]
    # runs arrive newest first; walk oldest first to detect a change
    ordered = sorted(ordered, key=lambda run: str(run.get("as_of_date") or ""))
    if not ordered:
        return {"status": "empty", "current": [], "changes": []}

    changes: list[dict[str, Any]] = []
    previous: dict[str, Any] = {}
    for run in ordered:
        config = _run_config(run)
        if previous:
            for key, label, _unit in RULE_LABELS:
                before, after = previous.get(key), config.get(key)
                if before is not None and after is not None and before != after:
                    changes.append(
                        {
                            "date": str(run.get("as_of_date") or ""),
                            "key": key,
                            "label": label,
                            "before": format_rule(key, before),
                            "after": format_rule(key, after),
                        }
                    )
        previous = {**previous, **config}

    latest = _run_config(ordered[-1])
    current = [
        {"key": key, "label": label, "unit": unit, "value": format_rule(key, latest.get(key))}
        for key, label, unit in RULE_LABELS
        if latest.get(key) is not None
    ]
    return {
        "status": "available",
        "current": current,
        "changes": list(reversed(changes))[:20],
        "since": str(ordered[0].get("as_of_date") or ""),
        "as_of": str(ordered[-1].get("as_of_date") or ""),
    }
