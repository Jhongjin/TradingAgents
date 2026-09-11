"""`/lab/gold`: the pattern chart, served from the same deployment.

Deliberately apart from the product. It uses none of the site's shell, appears
in no menu, is absent from the sitemap, and asks robots not to index it. The
Korean equity service and this private chart share a deployment and nothing
else.

Bars are fetched per request and the patterns are found on the spot, both of
which are fast. The win rates are not: measuring years of bars takes minutes, so
the page quotes a measurement stored earlier by the lab's own command.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

DEFAULT_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d", "1wk", "1mo")
DEFAULT_INTERVAL = "1h"
STUDY_LABEL_PREFIX = "gold"
DATA_PATH = "/lab/gold/data"


def study_label(symbol: str, interval: str) -> str:
    return f"{STUDY_LABEL_PREFIX}:{symbol}:{interval}"


def load_stored_study(repo: Any, symbol: str, interval: str) -> dict[str, Any] | None:
    """The measurement the lab pushed, or None when it has not been run."""

    if repo is None:
        return None
    try:
        row = repo.latest_backtest_run(label=study_label(symbol, interval))
    except Exception:
        return None
    if not row:
        return None
    payload = (row.get("metrics_json") or {}).get("study")
    return dict(payload) if isinstance(payload, Mapping) else None


def build_gold_frame(*, repo: Any = None, symbol: str = "GC=F", interval: str = DEFAULT_INTERVAL, bars: int = 600, min_stars: int = 3) -> dict[str, Any]:
    """One timeframe, fetched now: what the page asks for on a tab or a timer.

    Raises when the vendor has nothing, so the route can answer with a status
    the page understands instead of an empty chart.
    """

    from goldlab.chart import build_frame
    from goldlab.data import fetch_bars

    series = fetch_bars(symbol, interval=interval)
    if len(series) < 60:
        raise RuntimeError(f"only {len(series)} bars for {symbol} {interval}")
    return build_frame(series, study=load_stored_study(repo, symbol, interval), max_bars=bars, min_stars=min_stars)


def render_gold_chart_page(
    *,
    repo: Any = None,
    symbol: str = "GC=F",
    intervals: Sequence[str] = DEFAULT_INTERVALS,
    bars: int = 600,
    min_stars: int = 3,
    default_interval: str = DEFAULT_INTERVAL,
    data_url: str | None = DATA_PATH,
) -> str:
    """Draw the first timeframe now; the page fetches the rest as they are asked for.

    With a data URL only the opening timeframe is fetched here, which keeps the
    request short and lets the page refresh itself. Without one, every
    timeframe is fetched and inlined and the page is static.
    """

    from goldlab.chart import render_chart

    wanted = list(intervals) or list(DEFAULT_INTERVALS)
    first = default_interval if default_interval in wanted else wanted[0]
    to_fetch = [first] if data_url else wanted

    frames: dict[str, dict[str, Any]] = {}
    for interval in to_fetch:
        # One timeframe failing must not take the page with it: the vendor
        # rate-limits, and a host can refuse a directory the lab wants.
        try:
            frames[interval] = build_gold_frame(repo=repo, symbol=symbol, interval=interval, bars=bars, min_stars=min_stars)
        except Exception:
            continue
    if not frames and not data_url:
        return (
            "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            "<meta name=\"robots\" content=\"noindex, nofollow\">"
            "<title>차트를 불러오지 못했습니다</title></head>"
            "<body style=\"background:#0e1117;color:#e8ebf2;font-family:system-ui;padding:40px\">"
            "<h1>시세를 불러오지 못했습니다</h1>"
            "<p>잠시 뒤 새로고침해 주세요. 시세 제공처가 응답하지 않으면 차트를 그릴 수 없습니다.</p>"
            "</body></html>"
        )
    return render_chart(
        frames,
        symbol=symbol,
        default_interval=first,
        intervals=wanted,
        data_url=data_url,
        bars=bars,
    )
