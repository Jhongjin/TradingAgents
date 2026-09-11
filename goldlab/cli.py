"""Command line for the gold pattern lab.

    python -m goldlab fetch --interval 1h
    python -m goldlab patterns --interval 1h --last 20
    python -m goldlab study --interval 1h --horizons 4,12,24,72

Runs on the operator's own machine against a local cache. Nothing here touches
the public site or any account.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from .contracts import CONTRACTS, GOLD_FUTURES
from .data import INTERVAL_MAX_DAYS, cache_path, load_bars
from .patterns import PATTERN_REGISTRY, detect_patterns
from .live import DEFAULT_INTERVALS, save_study, scan_live
from .chart import build_frame, render_chart
from .events import events_file, write_events_template
from .report import render_report
from .study import DEFAULT_HORIZONS, run_pattern_study

app = typer.Typer(help="Gold futures chart-pattern lab (private).", no_args_is_help=True)
console = Console()


def _parse_horizons(raw: str) -> tuple[int, ...]:
    values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    return tuple(value for value in values if value > 0) or DEFAULT_HORIZONS


@app.command("fetch")
def fetch_command(
    symbol: str = typer.Option("GC=F", "--symbol", help="GC=F (100oz) or MGC=F (10oz)."),
    interval: str = typer.Option("1h", "--interval", help=f"One of {', '.join(INTERVAL_MAX_DAYS)}."),
    days: Optional[int] = typer.Option(None, "--days", help="How far back; capped by what the vendor serves."),
):
    """Download bars and cache them on disk."""

    series = load_bars(symbol, interval=interval, days=days, refresh=True)
    console.print(
        f"[green]{len(series)} bars[/green] {series.symbol} {series.interval} "
        f"{series.first} → {series.last}"
    )
    console.print(f"[dim]cached at {cache_path(symbol, interval)}[/dim]")


@app.command("patterns")
def patterns_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    interval: str = typer.Option("1h", "--interval"),
    last: int = typer.Option(20, "--last", min=1, max=200, help="How many recent hits to show."),
    only: Optional[str] = typer.Option(None, "--only", help="Comma-separated pattern names."),
):
    """List the most recent pattern hits in the cached bars."""

    series = load_bars(symbol, interval=interval)
    wanted = [name.strip() for name in only.split(",")] if only else None
    hits = detect_patterns(series, patterns=wanted)
    if not hits:
        console.print("[yellow]no hits[/yellow]")
        return

    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit.pattern] = counts.get(hit.pattern, 0) + 1
    summary = Table(box=box.SIMPLE_HEAD, title=f"{len(hits)} hits in {len(series)} bars")
    summary.add_column("패턴")
    summary.add_column("방향")
    summary.add_column("횟수", justify="right")
    for name, count in sorted(counts.items(), key=lambda item: -item[1]):
        label, direction, _detector = PATTERN_REGISTRY[name]
        summary.add_row(label, "상승" if direction == "bullish" else "하락", str(count))
    console.print(summary)

    recent = Table(box=box.SIMPLE_HEAD, title=f"최근 {min(last, len(hits))}건")
    for column in ("시각", "패턴", "방향", "가격"):
        recent.add_column(column)
    for hit in hits[-last:]:
        recent.add_row(
            hit.timestamp.strftime("%Y-%m-%d %H:%M"),
            hit.label,
            "상승" if hit.direction == "bullish" else "하락",
            f"{hit.price:,.1f}",
        )
    console.print(recent)


@app.command("study")
def study_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    interval: str = typer.Option("1h", "--interval"),
    horizons: str = typer.Option("4,12,24,72", "--horizons", help="Forward bars to measure."),
    min_occurrences: int = typer.Option(30, "--min", min=5, help="Below this, a pattern is not reported as tradable."),
    output: Optional[Path] = typer.Option(None, "--output", help="Write the full result JSON here."),
):
    """Measure what followed each pattern, against the base rate of the same bars."""

    series = load_bars(symbol, interval=interval)
    spec = CONTRACTS.get(symbol, GOLD_FUTURES)
    result = run_pattern_study(series, horizons=_parse_horizons(horizons), min_occurrences=min_occurrences, contract=spec)

    console.print(
        f"[bold]{result.symbol} {result.interval}[/bold] {result.bars} bars · "
        f"{result.start[:16]} → {result.end[:16]}"
    )
    for horizon in result.horizons:
        base = result.base_rate[horizon]["long"]
        console.print(
            f"[dim]기준({horizon}봉): 승률 {base['win_rate']:.1%} · 평균 {base['average_return']:+.4%}[/dim]"
        )

    for horizon in result.horizons:
        table = Table(box=box.SIMPLE_HEAD, title=f"{horizon}봉 뒤")
        for column in ("패턴", "방향", "표본", "승률", "기준대비 승률", "기준대비 수익", "t", "1계약 손익"):
            table.add_column(column)
        rows = 0
        for row in result.patterns:
            stats = row["horizons"].get(str(horizon)) or {}
            if not stats.get("enough_samples"):
                continue
            rows += 1
            table.add_row(
                row["label"],
                "상승" if row["direction"] == "bullish" else "하락",
                str(stats["count"]),
                f"{stats['win_rate']:.1%}",
                f"{stats.get('edge_win_rate', 0):+.1%}",
                f"{stats.get('edge_return', 0):+.3%}",
                str(stats.get("t_stat")),
                f"{stats.get('money_per_trade', 0):,.0f}",
            )
        if rows:
            console.print(table)
        else:
            console.print(f"[yellow]{horizon}봉: 표본 {min_occurrences}회를 넘긴 패턴이 없습니다.[/yellow]")

    for note in result.notes:
        console.print(f"[yellow]{note}[/yellow]")

    stored = save_study(result.as_dict(), symbol=symbol, interval=interval)
    console.print(f"[dim]measurement stored at {stored}[/dim]")
    if output is not None:
        output.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[dim]saved {output}[/dim]")




@app.command("now")
def now_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    intervals: str = typer.Option(",".join(DEFAULT_INTERVALS), "--intervals", help="Timeframes to scan, comma separated."),
    recent: int = typer.Option(3, "--recent", min=1, max=20, help="How many bars back still counts as 'now'."),
    horizon: Optional[int] = typer.Option(None, "--horizon", help="Quote the record at this horizon instead of the strongest."),
    measure: bool = typer.Option(False, "--measure", help="Re-measure the history before quoting it."),
    offline: bool = typer.Option(False, "--offline", help="Use the cached bars instead of fetching."),
    output: Optional[Path] = typer.Option(None, "--output", help="Write the scan JSON here."),
):
    """What has just formed on each timeframe, with the record that follows it."""

    wanted = [name.strip() for name in intervals.split(",") if name.strip()]
    scan = scan_live(
        symbol,
        intervals=wanted,
        recent_bars=recent,
        horizon=horizon,
        refresh=not offline,
        refresh_study=measure,
    )

    status = Table(box=box.SIMPLE_HEAD, title=f"{symbol} · {scan.generated_at[:16]}")
    for column in ("주기", "상태", "봉", "마지막", "현재가"):
        status.add_column(column)
    for row in scan.intervals:
        status.add_row(
            row["interval"],
            row.get("status", "-"),
            str(row.get("bars", "-")),
            str(row.get("last_timestamp", "-"))[:16],
            f"{row['last_price']:,.1f}" if row.get("last_price") else "-",
        )
    console.print(status)

    bias = scan.bias()
    colour = "green" if bias["direction"] == "상승 우세" else ("red" if bias["direction"] == "하락 우세" else "yellow")
    console.print(f"[{colour}]종합: {bias['direction']}[/{colour}] [dim](판정에 쓰인 신호 {bias['counted']}개)[/dim]")

    if not scan.signals:
        console.print("[yellow]지금 완성된 패턴이 없습니다.[/yellow]")
        return

    table = Table(box=box.SIMPLE_HEAD, title=f"최근 {recent}봉 안에 완성된 패턴 {len(scan.signals)}건")
    for column in ("주기", "패턴", "방향", "시각", "승률", "기준대비", "표본", "t", "예상 상단", "예상 하단", "신뢰도"):
        table.add_column(column)
    for signal in scan.signals:
        table.add_row(
            signal.interval,
            signal.label,
            "상승" if signal.direction == "bullish" else "하락",
            signal.timestamp[5:16].replace("T", " "),
            f"{signal.win_rate:.1%}" if signal.win_rate is not None else "-",
            f"{signal.edge_win_rate:+.1%}" if signal.edge_win_rate is not None else "-",
            str(signal.samples or "-"),
            str(signal.t_stat if signal.t_stat is not None else "-"),
            f"{signal.upside_price:,.1f}" if signal.upside_price else "-",
            f"{signal.downside_price:,.1f}" if signal.downside_price else "-",
            signal.confidence,
        )
    console.print(table)

    for note in scan.notes:
        console.print(f"[yellow]{note}[/yellow]")

    if output is not None:
        output.write_text(json.dumps(scan.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[dim]saved {output}[/dim]")


@app.command("watch")
def watch_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    intervals: str = typer.Option(",".join(DEFAULT_INTERVALS), "--intervals"),
    every: int = typer.Option(300, "--every", min=30, help="Seconds between scans."),
    recent: int = typer.Option(2, "--recent", min=1, max=20),
    rounds: int = typer.Option(0, "--rounds", min=0, help="Stop after this many scans; 0 runs until interrupted."),
):
    """Re-scan on a timer and print only what is new."""

    import time

    seen: set[tuple[str, str, str]] = set()
    count = 0
    while rounds == 0 or count < rounds:
        count += 1
        scan = scan_live(symbol, intervals=[name.strip() for name in intervals.split(",") if name.strip()], recent_bars=recent)
        fresh = [signal for signal in scan.signals if (signal.interval, signal.pattern, signal.timestamp) not in seen]
        for signal in fresh:
            seen.add((signal.interval, signal.pattern, signal.timestamp))
        stamp = scan.generated_at[11:16]
        if fresh:
            for signal in fresh:
                arrow = "▲" if signal.direction == "bullish" else "▼"
                console.print(
                    f"[{'green' if signal.direction == 'bullish' else 'red'}]{arrow} {stamp} {signal.interval} {signal.label}[/] "
                    f"승률 {signal.win_rate:.0%} (기준대비 {signal.edge_win_rate:+.0%}) · 표본 {signal.samples} · {signal.confidence}"
                    if signal.win_rate is not None
                    else f"{arrow} {stamp} {signal.interval} {signal.label} · 표본 부족"
                )
        else:
            console.print(f"[dim]{stamp} 새로 완성된 패턴 없음 · 종합 {scan.bias()['direction']}[/dim]")
        if rounds and count >= rounds:
            break
        time.sleep(every)


@app.command("report")
def report_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    intervals: str = typer.Option(",".join(DEFAULT_INTERVALS), "--intervals"),
    recent: int = typer.Option(5, "--recent", min=1, max=30),
    measure: bool = typer.Option(False, "--measure", help="Re-measure the history before writing the page."),
    offline: bool = typer.Option(False, "--offline", help="Use the cached bars instead of fetching."),
    output: Path = typer.Option(Path("gold-patterns.html"), "--output", help="Where to write the page."),
    open_it: bool = typer.Option(True, "--open/--no-open", help="Open the page in the browser when done."),
):
    """Write a local page: what is live now, and the record behind each pattern."""

    wanted = [name.strip() for name in intervals.split(",") if name.strip()]
    scan = scan_live(symbol, intervals=wanted, recent_bars=recent, refresh=not offline, refresh_study=measure)
    output.write_text(render_report(scan, intervals=wanted), encoding="utf-8")
    console.print(f"[green]{output}[/green] · 패턴 {len(scan.signals)}건 · 종합 {scan.bias()['direction']}")
    if open_it:
        import webbrowser

        webbrowser.open(output.resolve().as_uri())


@app.command("chart")
def chart_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    intervals: str = typer.Option("5m,15m,1h,4h,1d", "--intervals"),
    bars: int = typer.Option(700, "--bars", min=120, max=2000, help="Bars per timeframe to draw."),
    stars: int = typer.Option(3, "--stars", min=1, max=3, help="Minimum importance for an economic release."),
    offline: bool = typer.Option(False, "--offline", help="Use the cached bars instead of fetching."),
    output: Path = typer.Option(Path("gold-chart.html"), "--output"),
    open_it: bool = typer.Option(True, "--open/--no-open"),
):
    """Draw the candles with patterns, sessions and releases marked on them."""

    from .live import load_study

    frames = {}
    for interval in [name.strip() for name in intervals.split(",") if name.strip()]:
        try:
            series = load_bars(symbol, interval=interval, refresh=not offline)
        except Exception as exc:
            console.print(f"[yellow]{interval}: {exc.__class__.__name__}[/yellow]")
            continue
        if len(series) < 60:
            console.print(f"[yellow]{interval}: 봉이 {len(series)}개뿐이라 건너뜁니다[/yellow]")
            continue
        frames[interval] = build_frame(series, study=load_study(symbol, interval), max_bars=bars, min_stars=stars)
        marked = len(frames[interval]["hits"])
        console.print(f"[dim]{interval}: {len(frames[interval]['bars'])}봉 · 패턴 {marked}건 · 지표 {len(frames[interval]['events'])}건[/dim]")
    if not frames:
        raise typer.BadParameter("no timeframe could be drawn")

    output.write_text(render_chart(frames, symbol=symbol), encoding="utf-8")
    console.print(f"[green]{output}[/green]")
    if open_it:
        import webbrowser

        webbrowser.open(output.resolve().as_uri())


@app.command("events")
def events_command(
    show: bool = typer.Option(True, "--show/--no-show", help="Print what is currently scheduled."),
    init: bool = typer.Option(False, "--init", help="Create the file for dates that follow no rule."),
):
    """The releases the chart marks, and where to add the ones set by committee."""

    from datetime import datetime, timedelta, timezone

    from .events import macro_events

    if init:
        created = write_events_template()
        console.print(f"[green]{created}[/green] 에 일정 파일을 만들었습니다. FOMC·CPI 날짜를 여기에 적으세요.")
    console.print(f"[dim]일정 파일: {events_file()}[/dim]")
    if not show:
        return
    now = datetime.now(timezone.utc)
    rows = macro_events(now - timedelta(days=30), now + timedelta(days=45), min_stars=2)
    if not rows:
        console.print("[yellow]표시할 일정이 없습니다.[/yellow]")
        return
    table = Table(box=box.SIMPLE_HEAD, title="최근 30일 / 향후 45일")
    for column in ("현지 시각", "등급", "지표", "출처"):
        table.add_column(column)
    for row in rows:
        when = datetime.fromisoformat(row["timestamp"]).astimezone()
        table.add_row(when.strftime("%Y-%m-%d %H:%M"), "★" * int(row["stars"]), row["name"], "규칙" if row["source"] == "rule" else "입력")
    console.print(table)


@app.command("publish")
def publish_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    intervals: str = typer.Option("15m,1h,4h,1d", "--intervals"),
    base_url: str = typer.Option("https://agenttrust.kr", "--base-url"),
    token: Optional[str] = typer.Option(None, "--token", help="Operator token; falls back to OPERATOR_ACCESS_CODE."),
):
    """Send the local measurements to the web chart so it can quote them."""

    import os

    import requests

    from .live import load_study

    secret = token or os.getenv("OPERATOR_ACCESS_CODE") or os.getenv("TRADINGAGENTS_WORKER_TOKEN")
    if not secret:
        raise typer.BadParameter("operator token required (--token or OPERATOR_ACCESS_CODE)")

    for interval in [name.strip() for name in intervals.split(",") if name.strip()]:
        study = load_study(symbol, interval)
        if not study:
            console.print(f"[yellow]{interval}: 측정 결과가 없습니다. study 를 먼저 실행하세요.[/yellow]")
            continue
        response = requests.post(
            f"{base_url.rstrip('/')}/api/admin/lab/gold/study",
            json={"symbol": symbol, "interval": interval, "study": study},
            headers={"X-TradingAgents-Worker-Token": secret},
            timeout=60,
        )
        if response.status_code >= 400:
            console.print(f"[red]{interval}: {response.status_code} {response.text[:120]}[/red]")
            continue
        body = response.json()
        console.print(f"[green]{interval}[/green] 패턴 {body.get('patterns')}건 전송")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
