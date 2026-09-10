"""Record one day of the harness paper account, with the benchmark beside it.

The account is derived by replaying fills, which can only ever answer "what do
we hold now". A day that closes without a row cannot be reconstructed later, so
this runs after the Korean market close and writes exactly one row per day.
That row is what the equity curve, the drawdown and the KOSPI comparison are
drawn from.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from tradingagents.harness.paper_state import build_paper_account_payload, default_initial_cash
from tradingagents.storage import PaperAccountSnapshotInput, StorageRepository

KST = ZoneInfo("Asia/Seoul")
BENCHMARK_SYMBOL = "^KS11"
BENCHMARK_NAME = "KOSPI"

PriceLoader = Callable[[list[str]], Mapping[str, float]]
BenchmarkLoader = Callable[[str], float | None]


def _default_price_loader(tickers: list[str]) -> dict[str, float]:
    from .market_api import build_latest_prices_payload

    if not tickers:
        return {}
    payload = build_latest_prices_payload(tickers, ignore_errors=True, max_tickers=max(len(tickers), 1))
    prices: dict[str, float] = {}
    for code, item in (payload.get("prices") or {}).items():
        close = item.get("close")
        if close:
            prices[str(code)] = float(close)
    return prices


def _default_benchmark_loader(on_date: str) -> float | None:
    from tradingagents.dataflows.kr_returns import fetch_benchmark_close

    return fetch_benchmark_close(BENCHMARK_SYMBOL, on_date=on_date)


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.0001"))
    except Exception:
        return Decimal("0")


def record_paper_account_snapshot(
    repo: StorageRepository | None,
    *,
    as_of: date | str | None = None,
    initial_cash: float | None = None,
    account_key: str = "paper",
    price_loader: PriceLoader | None = None,
    benchmark_loader: BenchmarkLoader | None = None,
) -> dict[str, Any]:
    """Write today's account row. Re-running the same day overwrites it."""

    if repo is None:
        return {"status": "not_configured"}
    initial_cash = default_initial_cash() if initial_cash is None else initial_cash
    if isinstance(as_of, str):
        snapshot_date = datetime.strptime(as_of[:10], "%Y-%m-%d").date()
    else:
        snapshot_date = as_of or datetime.now(KST).date()

    raw = build_paper_account_payload(repo, initial_cash=initial_cash, broker=account_key)
    if raw.get("status") in {"not_configured", "unavailable"}:
        return {"status": raw.get("status"), "error": raw.get("error")}

    codes = [str(item.get("ticker_code")) for item in (raw.get("positions") or []) if item.get("ticker_code")]
    notes: list[str] = []
    prices: dict[str, float] = {}
    if codes:
        try:
            prices = dict((price_loader or _default_price_loader)(codes))
        except Exception as exc:
            notes.append(f"prices unavailable ({exc.__class__.__name__})")
    priced = build_paper_account_payload(repo, initial_cash=initial_cash, current_prices=prices, broker=account_key)
    summary = priced.get("summary") or {}

    benchmark_close = None
    try:
        benchmark_close = (benchmark_loader or _default_benchmark_loader)(snapshot_date.isoformat())
    except Exception as exc:
        notes.append(f"benchmark unavailable ({exc.__class__.__name__})")

    # The curve compares like with like: both returns are measured from the
    # first recorded day, so a benchmark reading only helps once a first one
    # exists to anchor it.
    benchmark_return = None
    try:
        history = repo.list_paper_account_snapshots(account_key=account_key, limit=400)
    except Exception as exc:
        # the snapshot table is created by a migration; say so plainly instead
        # of failing the cron with a 500
        return {"status": "storage_unavailable", "error": f"{exc.__class__.__name__}: {exc}", "snapshot_date": snapshot_date.isoformat()}
    baseline = next((row for row in history if row.get("benchmark_close")), None)
    if benchmark_close and baseline and baseline.get("snapshot_date") != snapshot_date:
        try:
            benchmark_return = round((float(benchmark_close) / float(baseline["benchmark_close"])) - 1, 6)
        except (TypeError, ValueError, ZeroDivisionError):
            benchmark_return = None
    elif benchmark_close and (not baseline or baseline.get("snapshot_date") == snapshot_date):
        benchmark_return = 0.0

    try:
        snapshot_id = repo.upsert_paper_account_snapshot(
            PaperAccountSnapshotInput(
                snapshot_date=snapshot_date,
                account_key=account_key,
                cash=_money(summary.get("cash")),
                holdings_value=_money(summary.get("holdings_value")),
                equity=_money(summary.get("equity")),
                initial_cash=_money(summary.get("initial_cash") or initial_cash),
                total_return=summary.get("total_return"),
                realized_pnl=_money(summary.get("realized_pnl")),
                position_count=int(summary.get("open_count") or 0),
                priced_count=int(summary.get("priced_count") or 0),
                benchmark_symbol=BENCHMARK_SYMBOL,
                benchmark_close=float(benchmark_close) if benchmark_close else None,
                benchmark_return=benchmark_return,
                metadata={"notes": notes} if notes else {},
            )
        )
    except Exception as exc:
        return {"status": "storage_unavailable", "error": f"{exc.__class__.__name__}: {exc}", "snapshot_date": snapshot_date.isoformat()}
    return {
        "status": "recorded",
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date.isoformat(),
        "equity": summary.get("equity"),
        "total_return": summary.get("total_return"),
        "benchmark_close": benchmark_close,
        "benchmark_return": benchmark_return,
        "position_count": summary.get("open_count"),
        "priced_count": summary.get("priced_count"),
        "notes": notes,
    }


def build_paper_curve_payload(repo: StorageRepository | None, *, account_key: str = "paper", limit: int = 400) -> dict[str, Any]:
    """The account curve against the benchmark, oldest first."""

    if repo is None:
        return {"status": "not_configured", "points": [], "summary": {}}
    try:
        rows = repo.list_paper_account_snapshots(account_key=account_key, limit=limit)
    except Exception as exc:
        return {"status": "unavailable", "error": f"{exc.__class__.__name__}: {exc}", "points": [], "summary": {}}
    if not rows:
        return {"status": "empty", "points": [], "summary": {}}

    points = []
    peak = None
    max_drawdown = 0.0
    for row in rows:
        equity = float(row.get("equity") or 0)
        peak = equity if peak is None else max(peak, equity)
        if peak:
            max_drawdown = min(max_drawdown, (equity / peak) - 1)
        when = row.get("snapshot_date")
        points.append(
            {
                "date": when.isoformat() if hasattr(when, "isoformat") else str(when),
                "equity": round(equity, 2),
                "total_return": row.get("total_return"),
                "benchmark_return": row.get("benchmark_return"),
                "position_count": int(row.get("position_count") or 0),
            }
        )

    last = points[-1]
    account_return = last.get("total_return")
    benchmark_return = last.get("benchmark_return")
    excess = None
    if account_return is not None and benchmark_return is not None:
        excess = round(float(account_return) - float(benchmark_return), 6)
    return {
        "status": "available",
        "points": points,
        "summary": {
            "day_count": len(points),
            "first_date": points[0]["date"],
            "last_date": last["date"],
            "account_return": account_return,
            "benchmark_return": benchmark_return,
            "benchmark_name": BENCHMARK_NAME,
            "excess_return": excess,
            "max_drawdown": round(max_drawdown, 6),
        },
    }
