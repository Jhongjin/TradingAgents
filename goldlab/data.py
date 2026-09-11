"""Bars for gold futures, cached on disk.

Every study here re-reads the same history many times, and the vendor limits
intraday range by interval. Bars are fetched once, stored as CSV under the
lab's cache, and read from there afterwards, so a study is reproducible and a
rate limit cannot change an answer halfway through.
"""

from __future__ import annotations

import csv
import os
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
}
RESAMPLED_FROM = {"4h": ("1h", 4)}


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

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
    raw = os.getenv("GOLDLAB_CACHE_DIR")
    path = Path(raw) if raw else Path.home() / ".goldlab" / "bars"
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    target = cache_path(series.symbol, series.interval)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for bar in series.bars:
            writer.writerow([bar.timestamp.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.volume])
    return target


def read_cache(symbol: str, interval: str) -> BarSeries | None:
    source = cache_path(symbol, interval)
    if not source.exists():
        return None
    bars: list[Bar] = []
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
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
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
        bars.append(Bar(timestamp=parsed, open=open_, high=high, low=low, close=close, volume=float(row.get("volume") or 0.0)))
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
            ladder = ((7, "7d"), (30, "1mo"), (60, "1mo"))
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
    write_cache(series)
    return series
