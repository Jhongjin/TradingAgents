"""The chart itself: candles, with everything drawn on top of them.

A table of pattern statistics is unreadable while a chart is open, so the
numbers come to the chart instead. This module builds them: bars, each detected
pattern with its record, the shapes still forming and the level they would
confirm at, the three trading sessions with their highs and lows, and the
American releases that move the market. `chart_view` draws them.

The page can stand alone with the data inlined, or be given a data URL, in
which case it fetches each symbol and timeframe when asked for and refreshes
the one on screen on a timer. Every clock on it reads Korean time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .context import ContextTagger
from .data import BarSeries
from .events import macro_events
from .indicators import moving_averages, trend_lines
from .patterns import PatternHit, detect_patterns
from .patterns.forming import attach_record, detect_forming
from .sessions import all_session_windows, session_summary
from .walkforward import METHOD as WALKFORWARD_METHOD, pick_record

KST = ZoneInfo("Asia/Seoul")
DAILY_OR_LONGER = {"1d", "1wk", "1mo"}
POLL_SECONDS = {"1m": 20, "2m": 20, "5m": 30, "15m": 30, "30m": 60, "1h": 60, "4h": 120, "1d": 300, "1wk": 600, "1mo": 600}
# How often the last candle is nudged with a fresh quote, apart from the full redraw.
QUOTE_SECONDS = {"1m": 5, "2m": 5, "5m": 5, "15m": 5, "30m": 10, "1h": 10, "4h": 10, "1d": 30, "1wk": 30, "1mo": 30}
BUCKET_SECONDS = {"1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400, "1wk": 604800, "1mo": 2678400}


def _confidence(stats: Mapping[str, Any]) -> str:
    if stats.get("confidence"):
        return str(stats["confidence"])   # walk-forward studies judge this on shrunk numbers and the FDR check
    samples = int(stats.get("count") or 0)
    edge = stats.get("edge_win_rate")
    t_stat = abs(float(stats.get("t_stat") or 0))
    if not samples:
        return "측정 없음"
    if edge is None or edge <= 0:
        return "기준 미달"
    if t_stat >= 3:
        return "강함"
    if t_stat >= 2:
        return "보통"
    return "약함"


def _best_stats(study: Mapping[str, Any] | None, *, min_samples: int) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for row in (study or {}).get("patterns") or []:
        best = None
        for stats in (row.get("horizons") or {}).values():
            if int(stats.get("count") or 0) < min_samples:
                continue
            if best is None or abs(stats.get("t_stat") or 0) > abs(best.get("t_stat") or 0):
                best = stats
        if best:
            lookup[str(row.get("pattern"))] = best
    return lookup


def _label_time(stamp: datetime, interval: str) -> str:
    local = stamp.astimezone(KST)
    return local.strftime("%Y-%m-%d") if interval in DAILY_OR_LONGER else local.strftime("%m-%d %H:%M")


def _bar_row(bar: Any, interval: str) -> list[Any]:
    """Label, OHLC, the epoch second the page uses to tell one candle from the next, and volume."""

    return [_label_time(bar.timestamp, interval), bar.open, bar.high, bar.low, bar.close, int(bar.timestamp.timestamp()), bar.volume]


def _delay_seconds(bars: Sequence[Any], now: datetime) -> int | None:
    """How far behind the clock the newest bar is: the vendor's delay, made visible.

    Exchange data for gold futures reaches the free feed about ten minutes late.
    A chart that hides that looks stuck; one that states it can be trusted.
    """

    if not bars:
        return None
    return max(0, int((now - bars[-1].timestamp.astimezone(KST)).total_seconds()))


def quote_payload(series: BarSeries, *, last: int = 3) -> dict[str, Any]:
    """The newest few candles only: what the page asks for every few seconds."""

    bars = series.bars[-last:]
    now = datetime.now(timezone.utc).astimezone(KST)
    return {
        "interval": series.interval,
        "bars": [_bar_row(bar, series.interval) for bar in bars],
        "bucket_seconds": BUCKET_SECONDS.get(series.interval, 60),
        "delay_seconds": _delay_seconds(bars, now),
        "last_price": bars[-1].close if bars else None,
        "last_time": bars[-1].timestamp.astimezone(KST).isoformat() if bars else None,
        "generated_at": now.isoformat(),
        "generated_label": now.strftime("%H:%M:%S"),
    }


def _quote(study: Mapping[str, Any] | None, pattern: str, context: Mapping[str, Any] | None, *, min_samples: int, legacy: dict[str, dict]) -> dict[str, Any]:
    """The record a hit is shown with, as flat fields the page reads.

    A walk-forward study gives the shrunk, context-matched record and says what
    it was matched on. An older stored study (no ``method``) still works, quoted
    as it always was and marked as unshrunk.
    """

    if study and study.get("method") == WALKFORWARD_METHOD:
        row = next((item for item in study.get("patterns") or [] if item.get("pattern") == pattern), None)
        picked = pick_record((row or {}).get("horizons") or {}, context, min_samples=min_samples)
        if not picked:
            return {"samples": 0, "win_rate": None, "edge_win_rate": None, "t_stat": None, "confidence": "측정 없음", "basis": "", "shrunk": True}
        stats = picked["stats"]
        return {
            "samples": int(stats.get("count") or 0),
            "win_rate": stats.get("shrunk_win_rate", stats.get("win_rate")),
            "raw_win_rate": stats.get("win_rate"),
            "edge_win_rate": stats.get("shrunk_edge_win_rate", stats.get("edge_win_rate")),
            "t_stat": stats.get("t_stat"),
            "confidence": _confidence(stats),
            "fdr": bool(stats.get("fdr_significant")),
            "basis": picked["basis"],
            "horizon": picked["horizon"],
            "shrunk": True,
        }
    stats = legacy.get(pattern) or {}
    return {
        "samples": int(stats.get("count") or 0),
        "win_rate": stats.get("win_rate"),
        "edge_win_rate": stats.get("edge_win_rate"),
        "t_stat": stats.get("t_stat"),
        "confidence": _confidence(stats),
        "basis": "전체 기간(구형 측정, 수축 없음)",
        "shrunk": False,
    }


def _hit_rows(
    hits: Sequence[PatternHit],
    study: Mapping[str, Any] | None,
    *,
    min_samples: int = 30,
    interval: str = "1h",
    context_at: Any = None,
) -> list[dict]:
    """Each hit with the measured record attached, ready to draw."""

    legacy = _best_stats(study, min_samples=min_samples)
    rows = []
    for hit in hits:
        context = context_at(hit.index) if context_at else None
        rows.append(
            {
                "index": hit.index,
                "time": hit.timestamp.astimezone(KST).isoformat(),
                "time_label": _label_time(hit.timestamp, interval),
                "pattern": hit.pattern,
                "label": hit.label,
                "direction": hit.direction,
                **_quote(study, hit.pattern, context, min_samples=min_samples, legacy=legacy),
            }
        )
    return rows


def summarise_bias(hits: Sequence[Mapping[str, Any]], forming: Sequence[Mapping[str, Any]], *, min_samples: int = 30) -> dict[str, Any]:
    """One line for the header, weighted by each shape's measured edge.

    A count of arrows would let a dozen doji outvote one flag with a record, so
    each contributes its edge over the base rate, and only with the samples to
    have earned a vote. A shape still forming counts at half weight: it has not
    happened yet.
    """

    up = down = 0.0
    counted_completed = counted_forming = 0
    weighted = [(row, 1.0, "completed") for row in hits] + [(row, 0.5, "forming") for row in forming]
    for row, scale, kind in weighted:
        edge = row.get("edge_win_rate")
        if int(row.get("samples") or 0) < min_samples or edge is None:
            continue
        # a walk-forward row earns full weight only by passing the false-discovery check
        proven = bool(row["fdr"]) if "fdr" in row else abs(float(row.get("t_stat") or 0)) >= 2
        weight = abs(float(edge)) * (1 if proven else 0.4) * scale
        if kind == "completed":
            counted_completed += 1
        else:
            counted_forming += 1
        signed = weight if float(edge) > 0 else -weight
        if row.get("direction") == "bullish":
            up += signed
        else:
            down += signed
    total = up + down
    base = {"up": round(up, 4), "down": round(down, 4), "completed": counted_completed, "forming": counted_forming}
    if (counted_completed + counted_forming) == 0 or total <= 0:
        return {"direction": "판단 보류", **base}
    share = up / total
    direction = "상승 우세" if share >= 0.65 else ("하락 우세" if share <= 0.35 else "혼재")
    return {"direction": direction, "up_share": round(share, 4), **base}


def _study_summary(study: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """What the stored measurement covers, for the page's tiles; None when there is none."""

    if not study:
        return None
    fdr = study.get("fdr") or {}
    return {
        "method": study.get("method") or "legacy",
        "tested": int(fdr.get("tested") or 0),
        "survivors": int(fdr.get("survivors") or 0),
        "signals": int(study.get("signals") or 0),
        "start": str(study.get("start") or "")[:10],
        "end": str(study.get("end") or "")[:10],
    }


def build_frame(
    series: BarSeries,
    *,
    study: Mapping[str, Any] | None = None,
    max_bars: int = 900,
    min_stars: int = 3,
    recent_hits: int = 40,
) -> dict[str, Any]:
    """Everything one timeframe needs, small enough to inline in a page."""

    interval = series.interval
    bars = series.bars[-max_bars:]
    trimmed = BarSeries(symbol=series.symbol, interval=interval, bars=bars)
    # contexts are read off the full series, so a hit near the left edge of the
    # drawn window still has the 200 bars behind it that its tags need
    offset = len(series.bars) - len(bars)
    tagger = ContextTagger(series.bars, interval=interval)
    hits = _hit_rows(detect_patterns(trimmed), study, interval=interval, context_at=lambda i: tagger.tag(i + offset).as_dict())
    forming = attach_record(detect_forming(bars), study, context=tagger.tag(len(series.bars) - 1).as_dict() if len(series.bars) else None)
    windows = all_session_windows(bars)

    stamp_index = {bar.timestamp: index for index, bar in enumerate(bars)}
    ordered = sorted(stamp_index)
    events = []
    if bars:
        for event in macro_events(bars[0].timestamp, bars[-1].timestamp, min_stars=min_stars):
            when = datetime.fromisoformat(event["timestamp"])
            index = None
            for candidate in ordered:
                if candidate <= when:
                    index = stamp_index[candidate]
                else:
                    break
            local = when.astimezone(KST)
            events.append({**event, "index": index, "local": local.isoformat(), "local_label": local.strftime("%m-%d %H:%M")})

    recent = [hit for hit in hits if hit["index"] >= len(bars) - recent_hits]
    now = datetime.now(timezone.utc).astimezone(KST)
    return {
        "interval": interval,
        "bars": [_bar_row(bar, interval) for bar in bars],
        "bucket_seconds": BUCKET_SECONDS.get(interval, 60),
        "hits": hits,
        "forming": forming,
        "ma": moving_averages(bars),
        "trendlines": trend_lines(bars),
        "bias": summarise_bias(recent, forming),
        "record_method": (study or {}).get("method") or "legacy",
        "ledger_line": (study or {}).get("ledger_line"),
        "study_summary": _study_summary(study),
        "sessions": windows,
        "session_rows": session_summary(windows, last=3),
        "events": events,
        "last_price": bars[-1].close if bars else 0.0,
        "last_time": bars[-1].timestamp.astimezone(KST).isoformat() if bars else None,
        "delay_seconds": _delay_seconds(bars, now) if interval not in DAILY_OR_LONGER else None,
        "generated_at": now.isoformat(),
        "generated_label": now.strftime("%H:%M:%S"),
    }


def render_chart(
    frames: Mapping[str, Mapping[str, Any]],
    *,
    symbol: str = "GC=F",
    default_interval: str | None = None,
    title: str | None = None,
    intervals: Sequence[str] | None = None,
    data_url: str | None = None,
    bars: int = 600,
    symbols: Sequence[Mapping[str, Any]] | None = None,
    chart_src: str | None = None,
) -> str:
    """One page holding every timeframe, or fetching them from ``data_url``.

    With no data URL the page is self-contained and static: what it shows is
    what was inlined. With one, the page is a shell that loads each symbol and
    timeframe when asked for and refreshes the one on screen on a timer, which
    is what makes the served chart live. The drawing lives in ``chart_view``.
    """

    from .chart_view import LIGHTWEIGHT_CHARTS_SRC, render_page

    order = list(intervals) if intervals else list(frames)
    for interval in frames:
        if interval not in order:
            order.append(interval)
    chosen = default_interval if default_interval in order else (order[0] if order else "1h")
    if chosen not in frames and not data_url:
        chosen = next(iter(frames), chosen)
    return render_page(
        frames,
        symbol=symbol,
        symbols=symbols,
        default_interval=chosen,
        order=order,
        data_url=data_url,
        bars=bars,
        poll_seconds=POLL_SECONDS,
        quote_seconds=QUOTE_SECONDS,
        title=title,
        chart_src=chart_src or LIGHTWEIGHT_CHARTS_SRC,
    )
