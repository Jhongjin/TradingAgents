"""Bars for gold futures, cached on disk.

Every study here re-reads the same history many times, and the vendor limits
intraday range by interval. Bars are fetched once, stored as CSV under the
lab's cache, and read from there afterwards, so a study is reproducible and a
rate limit cannot change an answer halfway through.
"""

from __future__ import annotations

import csv
import io
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

# Yahoo serves intraday only for a recent window, and the window shrinks as the
# interval does. Asking for more silently returns less, so the limit is stated.
INTERVAL_MAX_DAYS = {
    "1m": 7,
    "2m": 59,
    "5m": 59,
    "15m": 59,
    "30m": 59,
    "90m": 59,
    "60m": 730,
    "1h": 730,
    "4h": 730,   # resampled from 1h
    "1d": 20_000,
    "1wk": 20_000,
    "1mo": 20_000,
}
RESAMPLED_FROM = {"4h": ("1h", 4)}

# --------------------------------------------------------------------------
# KRX 금현물 (KRX gold spot), a different instrument from the COMEX future the
# rest of this module fetches: 99.99% bars priced in won per gram rather than
# dollars per ounce, traded on the Korean exchange, and buyable through the
# same account the harness trades stocks with.
#
# Daily is all this API serves. Its documented gubun switch is supposed to
# select daily, weekly or monthly, but all three values were checked and all
# three answer with daily bars, so the weekly view is grouped here instead of
# being asked for and quietly not delivered.
# --------------------------------------------------------------------------
KRX_GOLD_SYMBOLS = {"KRXGOLD", "KRX-GOLD", "M04020000"}
KRX_GOLD_RESAMPLED = {"1wk": 5}          # five sessions is a week on this market
KRX_GOLD_INTERVALS = ("1d", *KRX_GOLD_RESAMPLED)
KRX_GOLD_DEFAULT_DAYS = 600


def fetch_krx_gold_bars(*, interval: str = "1d", days: int | None = None) -> BarSeries:
    """Won-per-gram bars for KRX gold, through the NH client."""

    if interval not in KRX_GOLD_INTERVALS:
        raise ValueError(
            f"KRX gold has no {interval!r} bars; the exchange serves daily only, "
            f"so this offers {', '.join(KRX_GOLD_INTERVALS)}"
        )
    factor = KRX_GOLD_RESAMPLED.get(interval, 1)

    from tradingagents.execution.nh_client import NHClient, NHConfig

    # Quotes live on the live host whichever account is configured, and this
    # asks for prices only — it never touches an account or places an order.
    client = NHClient(config=NHConfig.from_env(paper=False))
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days or KRX_GOLD_DEFAULT_DAYS)
    raw = client.gold_candles(start=start.isoformat(), end=end.isoformat())

    rows = []
    for row in raw.get("Output_0") or []:
        stamp = _parse_krx_gold_date(str(row.get("bsop_date") or ""))
        if stamp is None:
            continue
        rows.append({
            "timestamp": stamp,
            "open": row.get("stck_oprc"),
            "high": row.get("stck_hgpr"),
            "low": row.get("stck_lwpr"),
            "close": row.get("stck_prpr"),
            "volume": row.get("acml_vol") or 0.0,
        })
    if not rows:
        raise RuntimeError(f"no KRX gold bars for {interval}")
    series = bars_from_rows(rows, symbol="KRXGOLD", interval="1d")
    return resample(series, factor=factor, interval=interval) if factor > 1 else series


def _parse_krx_gold_date(value: str) -> datetime | None:
    """NH dates these bars 26/09/18, which no general parser should have to guess."""

    parts = value.split("/")
    if len(parts) != 3:
        return None
    try:
        year, month, day = (int(part) for part in parts)
    except ValueError:
        return None
    return datetime(2000 + year, month, day, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    # where the bar came from; a vendor import outranks Yahoo for the same timestamp
    source: str = "yahoo"

    def as_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass(frozen=True)
class BarSeries:
    symbol: str
    interval: str
    bars: tuple[Bar, ...]

    def __len__(self) -> int:
        return len(self.bars)

    @property
    def first(self) -> datetime | None:
        return self.bars[0].timestamp if self.bars else None

    @property
    def last(self) -> datetime | None:
        return self.bars[-1].timestamp if self.bars else None

    def closes(self) -> list[float]:
        return [bar.close for bar in self.bars]

    def slice(self, start: datetime | None = None, end: datetime | None = None) -> "BarSeries":
        rows = [
            bar
            for bar in self.bars
            if (start is None or bar.timestamp >= start) and (end is None or bar.timestamp <= end)
        ]
        return BarSeries(symbol=self.symbol, interval=self.interval, bars=tuple(rows))


def cache_dir() -> Path:
    """Where bars are kept, somewhere that can actually be written.

    On a laptop that is the home directory. On a serverless host the home
    directory is mounted read-only, and asking for the path there raises before
    anything is even read, so the temporary area stands in: empty, writable, and
    good enough for a cache whose only job is to avoid a second download.
    """

    raw = os.getenv("GOLDLAB_CACHE_DIR")
    candidates: list[Path] = []
    if raw:
        candidates.append(Path(raw))
    else:
        try:
            candidates.append(Path.home() / ".goldlab" / "bars")
        except RuntimeError:  # no home directory at all
            pass
    candidates.append(Path(tempfile.gettempdir()) / "goldlab" / "bars")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return candidate
    return candidates[-1]


def cache_path(symbol: str, interval: str) -> Path:
    safe = symbol.replace("=", "_").replace("/", "_")
    return cache_dir() / f"{safe}__{interval}.csv"


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def write_cache(series: BarSeries) -> Path:
    _rewrite(series)
    return cache_path(series.symbol, series.interval)


CACHE_TAIL_ROWS = 12   # rows at the end of the file that an update may rewrite (refresh tail is 6)


def update_cache(file_bars: Sequence[Bar], merged: BarSeries, *, head_bytes: int | None = None) -> str:
    """Bring the CSV to ``merged`` without rewriting a file of hundreds of MB.

    ``file_bars`` is what the file holds now. When every bar except the last few
    is unchanged, the file is cut back to those rows and the rest appended;
    anything else (a gap filled in the middle, a vendor upgrade) falls back to a
    full atomic rewrite. Returns "noop", "append" or "rewrite".

    ``head_bytes`` set: ``file_bars`` and ``merged`` are only the file's tail (see
    ``read_cache_tail``), which starts at that byte. A rewrite then keeps the
    first ``head_bytes`` as they are and replaces only what follows.
    """

    target = cache_path(merged.symbol, merged.interval)
    have = len(file_bars)
    keep = max(0, have - CACHE_TAIL_ROWS)

    def rewrite() -> str:
        if head_bytes is None:
            _rewrite(merged)
        else:
            _splice(merged, head_bytes)
        return "rewrite"

    if not target.exists():
        if head_bytes:
            raise ValueError("a tail update needs the file it was read from")
        return rewrite()
    if have == 0 or len(merged.bars) < keep or tuple(merged.bars[:keep]) != tuple(file_bars[:keep]):
        return rewrite()
    if tuple(merged.bars) == tuple(file_bars):
        return "noop"
    drop = have - keep
    try:
        with target.open("r+b") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            block = min(size, 64 * 1024)
            handle.seek(size - block)
            lines = handle.read(block).splitlines(keepends=True)
            tail = lines[-drop:] if drop else []
            stamps = [(line.split(b",", 1)[0] or b"").decode("utf-8", "replace").strip() for line in tail]
            expect = [bar.timestamp.isoformat() for bar in file_bars[keep:]]
            if len(tail) != drop or stamps != expect or not lines[-1].endswith(b"\n"):
                raise ValueError("file tail does not match the parsed series")
            handle.truncate(size - sum(len(line) for line in tail))
        with target.open("a", newline="", encoding="utf-8") as out:
            writer = csv.writer(out)
            for bar in merged.bars[keep:]:
                writer.writerow([bar.timestamp.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.volume, bar.source])
        return "append"
    except (OSError, ValueError):
        return rewrite()


def _row_bytes(bar: Bar) -> bytes:
    out = io.StringIO()
    csv.writer(out).writerow([bar.timestamp.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.volume, bar.source])
    return out.getvalue().encode("utf-8")


def _splice(series: BarSeries, head_bytes: int) -> None:
    """Keep the file's first ``head_bytes`` and replace the rest with ``series``, atomically."""

    target = cache_path(series.symbol, series.interval)
    scratch = target.with_suffix(".csv.tmp")
    with target.open("rb") as source, scratch.open("wb") as handle:
        left = head_bytes
        while left > 0:
            chunk = source.read(min(left, 1 << 20))
            if not chunk:
                raise ValueError("the file is shorter than the head it was read with")
            handle.write(chunk)
            left -= len(chunk)
        for bar in series.bars:
            handle.write(_row_bytes(bar))
    os.replace(scratch, target)


def _parse_row(line: bytes) -> Bar | None:
    parts = line.decode("utf-8", "replace").strip().split(",")
    if len(parts) < 5:
        return None
    stamp = _parse_timestamp(parts[0])
    if stamp is None:
        return None
    try:
        return Bar(
            timestamp=stamp,
            open=float(parts[1]),
            high=float(parts[2]),
            low=float(parts[3]),
            close=float(parts[4]),
            volume=float(parts[5] or 0.0) if len(parts) > 5 else 0.0,
            source=(parts[6].strip() if len(parts) > 6 and parts[6].strip() else "yahoo"),
        )
    except ValueError:
        return None


def read_cache_tail(
    symbol: str, interval: str, *, since: datetime | None = None, rows: int | None = None
) -> tuple[BarSeries | None, int]:
    """The end of the CSV without reading the whole file: (bars, byte offset where they start).

    Reads backwards until it holds every bar at or after ``since`` and at least
    ``rows`` bars (whichever reaches further back), or the file's start. Always
    returns at least the last bar, so a caller can still see a gap. The offset
    lets ``update_cache(head_bytes=...)`` rewrite the tail and keep the rest.
    Returns (None, 0) when there is no usable file.
    """

    source = cache_path(symbol, interval)
    if not source.exists():
        return None, 0
    want_rows = max(1, rows or 0)
    block = 256 * 1024
    try:
        with source.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            position = size
            buffer = b""
            while True:
                step = min(block, position)
                position -= step
                handle.seek(position)
                buffer = handle.read(step) + buffer
                at_start = position == 0
                # the first line of the buffer may be cut, unless the buffer starts the file
                cut = 0 if at_start else buffer.find(b"\n") + 1
                if not at_start and cut == 0:
                    block *= 2
                    continue
                lines = buffer[cut:].splitlines(keepends=True)
                parsed = [(line, _parse_row(line)) for line in lines]
                bars = [bar for _line, bar in parsed if bar is not None]
                enough = len(bars) >= want_rows and (since is None or (bars and bars[0].timestamp < since))
                if enough or at_start:
                    break
                block = min(block * 2, 8 << 20)
    except OSError:
        return None, 0
    usable = [i for i, (_line, bar) in enumerate(parsed) if bar is not None]
    if not usable:
        return None, size
    # start at whichever reaches further back: the rows wanted or the first bar at/after since
    from_rows = usable[max(0, len(usable) - want_rows)]
    if since is None:
        first = from_rows
    else:
        from_since = next((i for i in usable if parsed[i][1].timestamp >= since), usable[-1])
        first = min(from_rows, from_since) if rows else from_since
    head = position + cut + sum(len(line) for line, _bar in parsed[:first])
    tail = tuple(bar for _line, bar in parsed[first:] if bar is not None)
    # only a strictly ordered tail of real rows can be spliced back
    if any(line and _bar is None and line.strip() for line, _bar in parsed[first:]):
        return None, 0
    return (BarSeries(symbol=symbol, interval=interval, bars=tail) if tail else None), head


def _rewrite(series: BarSeries) -> None:
    """Full rewrite through a temporary file so a crash never leaves half a store."""

    target = cache_path(series.symbol, series.interval)
    scratch = target.with_suffix(".csv.tmp")
    with scratch.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "source"])
        for bar in series.bars:
            writer.writerow([bar.timestamp.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.volume, bar.source])
    os.replace(scratch, target)


def read_cache(symbol: str, interval: str) -> BarSeries | None:
    source = cache_path(symbol, interval)
    if not source.exists():
        return None
    bars: list[Bar] = []
    try:
        with source.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                stamp = _parse_timestamp(row.get("timestamp"))
                if stamp is None:
                    continue
                try:
                    bars.append(
                        Bar(
                            timestamp=stamp,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row.get("volume") or 0.0),
                            source=str(row.get("source") or "yahoo"),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
    except (OSError, UnicodeDecodeError):
        # a file that is not text (a security agent can wrap files on a managed
        # laptop) is no cache at all, not a crash; the next fetch rewrites it
        return None
    return BarSeries(symbol=symbol, interval=interval, bars=tuple(bars)) if bars else None


def bars_from_rows(rows: Iterable[dict], *, symbol: str, interval: str) -> BarSeries:
    """Build a series from plain dicts; used by tests and by any other vendor."""

    bars: list[Bar] = []
    for row in rows:
        stamp = row.get("timestamp") or row.get("date")
        parsed = stamp if isinstance(stamp, datetime) else _parse_timestamp(stamp)
        if parsed is None:
            continue
        try:
            high = float(row["high"])
            low = float(row["low"])
            open_ = float(row["open"])
            close = float(row["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if high < low or high <= 0 or low <= 0:
            continue
        bars.append(Bar(timestamp=parsed, open=open_, high=high, low=low, close=close, volume=float(row.get("volume") or 0.0), source=str(row.get("source") or "yahoo")))
    bars.sort(key=lambda bar: bar.timestamp)
    return BarSeries(symbol=symbol, interval=interval, bars=tuple(bars))


def resample(series: BarSeries, *, factor: int, interval: str) -> BarSeries:
    """Group ``factor`` bars into one, keeping the true high, low and span."""

    if factor <= 1:
        return series
    grouped: list[Bar] = []
    for index in range(0, len(series.bars), factor):
        chunk = series.bars[index : index + factor]
        if not chunk:
            continue
        grouped.append(
            Bar(
                timestamp=chunk[0].timestamp,
                open=chunk[0].open,
                high=max(bar.high for bar in chunk),
                low=min(bar.low for bar in chunk),
                close=chunk[-1].close,
                volume=sum(bar.volume for bar in chunk),
            )
        )
    return BarSeries(symbol=series.symbol, interval=interval, bars=tuple(grouped))


YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; goldlab)"}


def _fetch_from_yahoo(symbol: str, interval: str, span_days: int) -> list[dict]:
    """Yahoo's chart endpoint over plain HTTPS.

    yfinance speaks through curl_cffi, which ignores the system trust store and
    fails outright on a network that inspects TLS. This asks the same service
    with the same client the rest of the repository uses, so one corporate
    proxy does not decide whether the lab has data.
    """

    import requests

    from tradingagents.dataflows.http_trust import apply_system_truststore_if_available

    apply_system_truststore_if_available()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=span_days)
    # Intraday is served by named range only; an epoch window that exceeds the
    # vendor's limit is refused outright rather than trimmed.
    params: dict[str, object] = {"interval": interval, "includePrePost": "false"}
    if interval in {"1m", "2m", "5m", "15m", "30m", "60m", "1h"}:
        ladder = ((7, "7d"), (30, "1mo"), (60, "3mo"), (180, "6mo"), (365, "1y"), (730, "2y"))
        if interval in {"1m", "2m", "5m", "15m", "30m", "90m"}:
            # the fine intervals are served for a much shorter window
            ladder = ((1, "1d"), (7, "7d"), (30, "1mo"), (60, "60d"))   # "1mo" would cut a 59-day ask to ~30 days
        for days, name in ladder:
            if span_days <= days:
                params["range"] = name
                break
        else:
            params["range"] = "2y"
    else:
        params["period1"] = int(start.timestamp())
        params["period2"] = int(end.timestamp()) + 86_400
    response = requests.get(
        YAHOO_CHART.format(symbol=symbol),
        params=params,
        headers=YAHOO_HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    results = ((payload.get("chart") or {}).get("result") or [])
    if not results:
        error = (payload.get("chart") or {}).get("error")
        raise RuntimeError(f"no chart data for {symbol} {interval}: {error}")
    result = results[0]
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    rows = []
    for position, stamp in enumerate(stamps):
        def _value(key: str):
            series = quote.get(key) or []
            return series[position] if position < len(series) else None

        close = _value("close")
        if close is None:
            continue
        rows.append(
            {
                "timestamp": datetime.fromtimestamp(int(stamp), tz=timezone.utc),
                "open": _value("open") if _value("open") is not None else close,
                "high": _value("high") if _value("high") is not None else close,
                "low": _value("low") if _value("low") is not None else close,
                "close": close,
                "volume": _value("volume") or 0.0,
            }
        )
    return rows


def fetch_bars(symbol: str = "GC=F", *, interval: str = "1h", days: int | None = None) -> BarSeries:
    """Download bars, honouring the vendor's window for the interval."""

    if symbol.upper() in KRX_GOLD_SYMBOLS:
        return fetch_krx_gold_bars(interval=interval, days=days)

    source_interval, factor = RESAMPLED_FROM.get(interval, (interval, 1))
    limit = INTERVAL_MAX_DAYS.get(source_interval)
    if limit is None:
        raise ValueError(f"unsupported interval {interval!r}")
    span = min(days or limit, limit)

    rows = _fetch_from_yahoo(symbol, source_interval, span)
    if not rows:
        raise RuntimeError(f"no bars returned for {symbol} {source_interval}")
    series = bars_from_rows(rows, symbol=symbol, interval=source_interval)
    if factor > 1:
        series = resample(series, factor=factor, interval=interval)
    return series


def load_bars(
    symbol: str = "GC=F",
    *,
    interval: str = "1h",
    days: int | None = None,
    refresh: bool = False,
) -> BarSeries:
    """Cached bars: read from disk unless asked to refresh."""

    if not refresh:
        cached = read_cache(symbol, interval)
        if cached and len(cached) > 0:
            return cached
    series = fetch_bars(symbol, interval=interval, days=days)
    if interval in RESAMPLED_FROM or symbol.upper() in KRX_GOLD_SYMBOLS:
        # resampled buckets are cut from the start of the fetched window, so two
        # windows would not line up; those series are replaced as before
        write_cache(series)
        return series
    # everything else accumulates: the vendor's window slides, the history stays
    from .barstore import merge_into_cache

    merged, _added = merge_into_cache(series)
    return merged
