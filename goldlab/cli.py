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

    if output is not None:
        output.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[dim]saved {output}[/dim]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
