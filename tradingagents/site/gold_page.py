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

DEFAULT_INTERVALS = ("15m", "1h", "4h", "1d")
STUDY_LABEL_PREFIX = "gold"


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


def render_gold_chart_page(
    *,
    repo: Any = None,
    symbol: str = "GC=F",
    intervals: Sequence[str] = DEFAULT_INTERVALS,
    bars: int = 600,
    min_stars: int = 3,
) -> str:
    """Fetch, detect, and draw. Any timeframe that fails is simply absent."""

    from goldlab.chart import build_frame, render_chart
    from goldlab.data import fetch_bars

    frames: dict[str, dict[str, Any]] = {}
    for interval in intervals:
        try:
            series = fetch_bars(symbol, interval=interval)
        except Exception:
            continue
        if len(series) < 60:
            continue
        frames[interval] = build_frame(
            series,
            study=load_stored_study(repo, symbol, interval),
            max_bars=bars,
            min_stars=min_stars,
        )
    if not frames:
        return (
            "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            "<meta name=\"robots\" content=\"noindex, nofollow\">"
            "<title>차트를 불러오지 못했습니다</title></head>"
            "<body style=\"background:#0e1117;color:#e8ebf2;font-family:system-ui;padding:40px\">"
            "<h1>시세를 불러오지 못했습니다</h1>"
            "<p>잠시 뒤 새로고침해 주세요. 시세 제공처가 응답하지 않으면 차트를 그릴 수 없습니다.</p>"
            "</body></html>"
        )
    return render_chart(frames, symbol=symbol, default_interval="1h" if "1h" in frames else None)
