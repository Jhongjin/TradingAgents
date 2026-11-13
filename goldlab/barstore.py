"""A bar store that remembers more than the vendor will serve.

Yahoo returns exactly 60 days of 5-minute bars and nothing older (GC=F and NQ=F
alike; it refuses a one-year ask). A pattern study and a signal ledger need
months, so history is accumulated: every fetch is merged into what is already
stored, and bars are only ever added.

Rules that keep the stored history trustworthy:

* A stored bar is not rewritten by a later fetch, except the last few of the
  series, which may have been fetched while still forming. Letting a vendor
  quietly restate old bars would change a signal after it was graded.
* Every bar carries a ``source``. Yahoo is the lowest rank; anything else (a
  Databento export, a CSV) outranks it. A vendor bar replaces a Yahoo bar for
  the same timestamp, and a Yahoo bar can never replace a vendor bar. So a
  one-time bulk import of years of 5-minute bars lands in the same store and
  the routine Yahoo fetch can not undo it.
* Nothing is deleted. A hole between stored history and a fresh fetch is
  reported as a gap, not papered over.

Caution for imports: a vendor's continuous contract (roll rule, back
adjustment) is not Yahoo's. Prices at the seam can differ by the roll gap. The
source tag makes the seam visible; it does not remove it.

Locally the store is the CSV cache the rest of the lab reads. The scheduled job
has no disk that survives, so it also keeps bars in the database through
``StorageRepository``; the file stays as the fallback when the tables are
missing or the database cannot be reached.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .data import Bar, BarSeries, _parse_timestamp, fetch_bars, read_cache, write_cache

# Bars at the end of the stored series whose values a new fetch may replace.
REFRESH_TAIL = 6
# A hole longer than this between stored history and a fresh fetch is reported.
# Three days spans a weekend plus a holiday on a market that closes for both.
GAP_DAYS = 3.0
INTRADAY = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}
# Intervals whose bars open on a fixed grid, in seconds. Yahoo ends its answer
# with a pseudo-bar stamped at the quote's own second (09:22:43), which is not a
# bar and must never be stored: history is never deleted, so a stray would stay.
GRID_SECONDS = {"1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1h": 3600}


def source_rank(source: str) -> int:
    """Yahoo is the fallback; every named vendor outranks it."""

    return 0 if (source or "yahoo") == "yahoo" else 1


def on_grid(series: BarSeries) -> BarSeries:
    """The series without bars that sit off the interval's time grid."""

    step = GRID_SECONDS.get(series.interval)
    if not step:
        return series
    kept = tuple(bar for bar in series.bars if int(bar.timestamp.timestamp()) % step == 0)
    return series if len(kept) == len(series.bars) else BarSeries(symbol=series.symbol, interval=series.interval, bars=kept)


def merge_bars(existing: Sequence[Bar], fresh: Sequence[Bar], *, refresh_tail: int = REFRESH_TAIL) -> tuple[Bar, ...]:
    """Union by timestamp.

    A fresh bar wins when its source outranks the stored one. At equal rank the
    stored bar is kept, except in the last ``refresh_tail`` bars. A lower rank
    never wins: Yahoo can not overwrite a vendor bar.
    """

    merged = {bar.timestamp: bar for bar in existing}
    ordered = sorted(existing, key=lambda item: item.timestamp)
    replaceable = {bar.timestamp for bar in ordered[-refresh_tail:]} if refresh_tail > 0 else set()
    for bar in fresh:
        current = merged.get(bar.timestamp)
        if current is None:
            merged[bar.timestamp] = bar
            continue
        gain = source_rank(bar.source) - source_rank(current.source)
        if gain > 0 or (gain == 0 and bar.timestamp in replaceable):
            merged[bar.timestamp] = bar
    return tuple(merged[stamp] for stamp in sorted(merged))


def _values(bar: Bar) -> tuple:
    return (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.source)


@dataclass
class SyncReport:
    symbol: str
    interval: str
    fetched: int = 0
    added: int = 0
    refreshed: int = 0
    total: int = 0
    first: str | None = None
    last: str | None = None
    gap: str | None = None
    db: str = "off"            # off | ok | unavailable
    db_inserted: int = 0
    db_updated: int = 0
    sources: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _to_rows(bars: Sequence[Bar]) -> list[dict[str, Any]]:
    return [
        {"ts": bar.timestamp, "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close, "volume": bar.volume, "source": bar.source}
        for bar in bars
    ]


def _count_sources(bars: Sequence[Bar]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bar in bars:
        counts[bar.source] = counts.get(bar.source, 0) + 1
    return counts


def load_history(symbol: str, interval: str, *, repo: Any = None) -> BarSeries | None:
    """Everything stored for the series: the file cache and, if given, the database."""

    cached = read_cache(symbol, interval)
    bars: tuple[Bar, ...] = cached.bars if cached else ()
    if repo is not None:
        try:
            stored = [
                Bar(
                    timestamp=row["ts"], open=row["open"], high=row["high"], low=row["low"], close=row["close"],
                    volume=row["volume"], source=row.get("source") or "yahoo",
                )
                for row in repo.goldlab_load_bars(symbol, interval)
            ]
        except Exception:
            stored = []
        if stored:
            # one history: the database is the durable copy, so it wins a tie
            bars = merge_bars(stored, bars, refresh_tail=0)
    return BarSeries(symbol=symbol, interval=interval, bars=bars) if bars else None


def merge_into_cache(series: BarSeries, *, refresh_tail: int = REFRESH_TAIL) -> tuple[BarSeries, int]:
    """Merge a fetched series into the CSV cache; returns the merged series and bars added."""

    series = on_grid(series)
    cached = read_cache(series.symbol, series.interval)
    before = cached.bars if cached else ()
    merged = BarSeries(symbol=series.symbol, interval=series.interval, bars=merge_bars(before, series.bars, refresh_tail=refresh_tail))
    write_cache(merged)
    return merged, len(merged.bars) - len(before)


def _persist(report: SyncReport, symbol: str, interval: str, merged: Sequence[Bar], repo: Any) -> None:
    """Write what differs from the database; a missing table leaves the file copy standing."""

    try:
        stored = {row["ts"]: (row["open"], row["high"], row["low"], row["close"], row["volume"], row.get("source") or "yahoo") for row in repo.goldlab_load_bars(symbol, interval)}
        # merge_bars already kept every stored value except the refresh tail and
        # vendor upgrades, so what differs from the database is exactly those
        changed = [bar for bar in merged if stored.get(bar.timestamp) != _values(bar)]
        outcome = repo.goldlab_upsert_bars(symbol, interval, _to_rows(changed))
        report.db = "ok"
        report.db_inserted = outcome["inserted"]
        report.db_updated = outcome["updated"]
    except Exception as exc:
        report.db = "unavailable"
        report.notes.append(f"DB 저장 실패, 파일 사본만 갱신했습니다: {exc.__class__.__name__}")


def sync_bars(
    symbol: str,
    interval: str,
    *,
    repo: Any = None,
    fetch: Callable[..., BarSeries] = fetch_bars,
    refresh_tail: int = REFRESH_TAIL,
) -> SyncReport:
    """Fetch the vendor's window and fold it into the stored history, file and database."""

    report = SyncReport(symbol=symbol, interval=interval)
    history = load_history(symbol, interval, repo=repo)
    before = history.bars if history else ()
    fresh = on_grid(fetch(symbol, interval=interval))
    report.fetched = len(fresh.bars)

    if before and fresh.bars and interval in INTRADAY:
        hole = fresh.bars[0].timestamp - before[-1].timestamp
        if hole > timedelta(days=GAP_DAYS):
            report.gap = f"{before[-1].timestamp.isoformat()} ~ {fresh.bars[0].timestamp.isoformat()}"
            report.notes.append("저장된 마지막 봉과 이번에 받은 첫 봉 사이가 비어 있습니다. 제공처가 이 구간을 더는 주지 않습니다.")

    merged = merge_bars(before, fresh.bars, refresh_tail=refresh_tail)
    old_by_ts = {bar.timestamp: bar for bar in before}
    report.added = sum(1 for bar in merged if bar.timestamp not in old_by_ts)
    report.refreshed = sum(1 for bar in merged if bar.timestamp in old_by_ts and _values(bar) != _values(old_by_ts[bar.timestamp]))
    report.total = len(merged)
    report.first = merged[0].timestamp.isoformat() if merged else None
    report.last = merged[-1].timestamp.isoformat() if merged else None
    report.sources = _count_sources(merged)

    write_cache(BarSeries(symbol=symbol, interval=interval, bars=merged))
    if repo is not None:
        _persist(report, symbol, interval, merged, repo)
    return report


# --------------------------------------------------------------------------
# one-time bulk import from another vendor
# --------------------------------------------------------------------------
def resample_by_time(bars: Sequence[Bar], *, step_seconds: int, interval: str, source: str) -> tuple[Bar, ...]:
    """Cut finer bars into time buckets (1m -> 5m): first open, extreme high/low, last close."""

    buckets: dict[int, list[Bar]] = {}
    for bar in sorted(bars, key=lambda item: item.timestamp):
        buckets.setdefault(int(bar.timestamp.timestamp()) // step_seconds, []).append(bar)
    out = []
    for key in sorted(buckets):
        chunk = buckets[key]
        out.append(
            Bar(
                timestamp=datetime.fromtimestamp(key * step_seconds, tz=timezone.utc),
                open=chunk[0].open,
                high=max(item.high for item in chunk),
                low=min(item.low for item in chunk),
                close=chunk[-1].close,
                volume=sum(item.volume for item in chunk),
                source=source,
            )
        )
    return tuple(out)


_NANOS = re.compile(r"(\.\d{6})\d+")


def read_vendor_csv(path: Path, *, source: str, symbol: str | None = None) -> list[Bar]:
    """Read an OHLCV CSV. Accepts ``timestamp``, ``ts_event`` or ``datetime`` for the time column.

    Databento's CSV (ISO time with nanoseconds, decimal prices) reads as is. If
    the file mixes several instruments, pass ``symbol`` to keep one raw symbol.
    """

    bars: list[Bar] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if symbol and row.get("symbol") and row["symbol"] != symbol:
                continue
            raw = row.get("timestamp") or row.get("ts_event") or row.get("datetime") or row.get("date")
            stamp = _parse_timestamp(_NANOS.sub(r"\1", str(raw or "")))
            if stamp is None:
                continue
            try:
                high, low = float(row["high"]), float(row["low"])
                if high < low or high <= 0 or low <= 0:
                    continue
                bars.append(Bar(timestamp=stamp, open=float(row["open"]), high=high, low=low, close=float(row["close"]), volume=float(row.get("volume") or 0.0), source=source))
            except (KeyError, TypeError, ValueError):
                continue
    return bars


def import_bars(
    path: Path,
    symbol: str,
    interval: str,
    *,
    source: str,
    from_interval: str | None = None,
    raw_symbol: str | None = None,
    repo: Any = None,
) -> SyncReport:
    """Merge a vendor file into the store; vendor bars replace Yahoo's, never the reverse.

    ``from_interval='1m'`` resamples 1-minute rows to ``interval`` first. Running
    the same import twice changes nothing.
    """

    if source_rank(source) == 0:
        raise ValueError("an import needs a vendor source tag other than 'yahoo'")
    report = SyncReport(symbol=symbol, interval=interval)
    rows = read_vendor_csv(path, source=source, symbol=raw_symbol)
    if from_interval and from_interval != interval:
        rows = list(resample_by_time(rows, step_seconds=GRID_SECONDS[interval], interval=interval, source=source))
    fresh = on_grid(BarSeries(symbol=symbol, interval=interval, bars=tuple(sorted(rows, key=lambda bar: bar.timestamp))))
    report.fetched = len(fresh.bars)
    history = load_history(symbol, interval, repo=repo)
    before = history.bars if history else ()
    merged = merge_bars(before, fresh.bars, refresh_tail=0)
    old_by_ts = {bar.timestamp: bar for bar in before}
    report.added = sum(1 for bar in merged if bar.timestamp not in old_by_ts)
    report.refreshed = sum(1 for bar in merged if bar.timestamp in old_by_ts and _values(bar) != _values(old_by_ts[bar.timestamp]))
    report.total = len(merged)
    report.first = merged[0].timestamp.isoformat() if merged else None
    report.last = merged[-1].timestamp.isoformat() if merged else None
    report.sources = _count_sources(merged)
    write_cache(BarSeries(symbol=symbol, interval=interval, bars=merged))
    if repo is not None:
        _persist(report, symbol, interval, merged, repo)
    report.notes.append("벤더 연속월물과 야후 연속월물은 롤 방식이 달라 경계에서 가격 차이가 날 수 있습니다. source 컬럼으로 구분됩니다.")
    return report


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
