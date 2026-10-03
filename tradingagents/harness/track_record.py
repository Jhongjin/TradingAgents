"""The account's own closed trades, put in front of the next decision.

Until 10-03 the harness decided every morning as if it had never traded: the
debate's portfolio manager was told to "reflect past lessons, if any" and was
never given any, and the post-trade review prompt existed but nothing fed it.
The closed round trips were already there, replayed from the fills for the
paper page. This turns them into a short record the confirmers can read.

Two rules keep it honest. Only trades that closed before the decision date
count, so a replay never sees its own future. And the record is evidence, not
a rule: it changes what the model reads, never a threshold. Rule changes stay
proposals until a person makes them.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

SMALL_SAMPLE = 20

EXIT_LABELS = {
    "stop_loss": "손절",
    "take_profit": "익절",
    "max_holding_days": "보유기간 만료",
    "news_risk": "뉴스 위험",
}

CONFIDENCE_BANDS = ((0.0, 0.6, "0.6 미만"), (0.6, 0.75, "0.6~0.75"), (0.75, 1.01, "0.75 이상"))


def _closed_before(closed: Iterable[Mapping[str, Any]], before: str | None) -> list[Mapping[str, Any]]:
    rows = [row for row in closed if row.get("realized_return") is not None and row.get("exit_date")]
    if before:
        rows = [row for row in rows if str(row["exit_date"])[:10] < before[:10]]
    return sorted(rows, key=lambda row: str(row["exit_date"]), reverse=True)


def _stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [float(row["realized_return"]) for row in rows]
    wins = sum(1 for value in returns if value > 0)
    return {
        "count": len(returns),
        "wins": wins,
        "hit_rate": round(wins / len(returns), 4) if returns else None,
        "average_return": round(sum(returns) / len(returns), 6) if returns else None,
    }


def summarize_closed(closed: Iterable[Mapping[str, Any]], *, before: str | None = None, recent: int = 5) -> dict[str, Any]:
    """Totals, then the same split by how each trade ended and how sure the entry was."""

    rows = _closed_before(closed, before)
    by_exit: dict[str, list] = defaultdict(list)
    by_band: dict[str, list] = defaultdict(list)
    for row in rows:
        by_exit[str(row.get("exit_reason") or "unknown")].append(row)
        confidence = row.get("decision_confidence")
        if confidence is None:
            continue
        for low, high, label in CONFIDENCE_BANDS:
            if low <= float(confidence) < high:
                by_band[label].append(row)
                break
    return {
        "as_of": before,
        **_stats(rows),
        "by_exit_reason": {reason: _stats(group) for reason, group in by_exit.items()},
        "by_confidence": {label: _stats(by_band[label]) for _, _, label in CONFIDENCE_BANDS if by_band.get(label)},
        "recent": [_trade(row) for row in rows[:recent]],
        "_rows": rows,
    }


def _trade(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ticker_code": row.get("ticker_code"),
        "ticker_name": row.get("ticker_name"),
        "entry_date": str(row.get("entry_date") or "")[:10],
        "exit_date": str(row.get("exit_date") or "")[:10],
        "exit_reason": row.get("exit_reason"),
        "realized_return": row.get("realized_return"),
        "decision_confidence": row.get("decision_confidence"),
    }


def ticker_trades(summary: Mapping[str, Any], code: str) -> list[dict[str, Any]]:
    wanted = str(code).upper()
    return [_trade(row) for row in summary.get("_rows", ()) if str(row.get("ticker_code") or "").upper() == wanted]


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:+.2f}%"


def _line(label: str, stats: Mapping[str, Any]) -> str:
    rate = stats.get("hit_rate")
    return f"{label} {stats['count']}건 · 승률 {'-' if rate is None else f'{rate * 100:.0f}%'} · 평균 {_pct(stats.get('average_return'))}"


def track_record_text(summary: Mapping[str, Any] | None, code: str | None = None) -> str:
    """A few lines of Korean the confirmers read as evidence. Empty when there is no record."""

    if not summary or not summary.get("count"):
        return ""
    lines = [f"이 계좌가 {summary.get('as_of') or '지금'} 이전에 청산한 거래: " + _line("전체", summary)]
    if summary["count"] < SMALL_SAMPLE:
        lines.append(f"(표본 {summary['count']}건 — 경향을 단정하지 말고 참고만 할 것)")
    for reason, stats in sorted(summary.get("by_exit_reason", {}).items(), key=lambda item: -item[1]["count"]):
        lines.append("- 청산 사유 " + _line(EXIT_LABELS.get(reason, reason), stats))
    for label, stats in summary.get("by_confidence", {}).items():
        lines.append("- 진입 확신도 " + _line(label, stats))
    if code:
        own = ticker_trades(summary, code)
        if own:
            lines.append(f"- 이 종목({code}) 과거 거래: " + "; ".join(
                f"{t['entry_date']}→{t['exit_date']} {EXIT_LABELS.get(str(t['exit_reason']), t['exit_reason'])} {_pct(t['realized_return'])}"
                for t in own[:3]))
        else:
            lines.append(f"- 이 종목({code})은 이 계좌에서 청산한 적이 없음")
    return "\n".join(lines)


def build_track_record(repo: Any, *, account_key: str, before: str | None) -> dict[str, Any] | None:
    """The account's record from the database, or None when there is nothing to read."""

    from .paper_state import build_paper_account_payload

    if repo is None or not hasattr(repo, "list_harness_fills"):
        return None
    # Prices are only needed to mark open positions; the closed trades carry
    # their own exit prices. An empty map keeps this off the network.
    payload = build_paper_account_payload(repo, account_key=account_key, current_prices={})
    if payload.get("status") in ("not_configured", "unavailable"):
        return None
    return summarize_closed(payload.get("closed") or [], before=before)


def public_summary(summary: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The summary without the raw rows, for storing beside a run."""

    if not summary:
        return None
    return {key: value for key, value in summary.items() if not key.startswith("_")}


ACCOUNT_LABELS = {"paper": "AI 확인 모의계좌", "rules": "규칙 전용 모의계좌", "kis": "KIS 모의투자 계좌"}


def review_track_record(llm: Any, summary: Mapping[str, Any], *, account_key: str, recent: int = 20) -> Any:
    """Run the post-trade review over the account's real record.

    The prompt has asked for rule changes since it was written; it was never
    run because nothing supplied paper_outcomes. What comes back is a proposal
    and is stored as one. Nothing here edits a rule.
    """

    from .prompts import get_prompt
    from .tasks import HarnessTask, run_task

    outcomes = {**(public_summary(summary) or {}), "recent": [_trade(row) for row in summary.get("_rows", ())[:recent]]}
    label = ACCOUNT_LABELS.get(account_key, account_key)
    task = HarnessTask(
        prompt=get_prompt("post_trade_review"),
        values={"target": f"{label} 전체 거래", "strategy": "스크리너 후보 확인 후 손절/익절 규칙 기반 스윙"},
        context={"paper_outcomes": outcomes, "track_record": track_record_text(summary)},
    )
    return run_task(task, llm)


def latest_run_id(repo: Any, *, account_key: str, limit: int = 30) -> str | None:
    """The newest executed (non dry-run) run of this account, where a review is filed."""

    for row in repo.list_harness_runs(limit=limit, public_only=False):
        metadata = row.get("metadata_json") or {}
        if not row.get("dry_run") and str(metadata.get("account_key") or "paper") == account_key:
            return str(row["id"])
    return None


__all__ = ["build_track_record", "latest_run_id", "public_summary", "review_track_record", "summarize_closed", "ticker_trades", "track_record_text"]
