"""Commands for the bar store, the signal ledger and the walk-forward study.

    python -m goldlab bars sync --symbol GC=F --intervals 5m
    python -m goldlab bars import export.csv --symbol GC=F --source databento --from-interval 1m
    python -m goldlab ledger scan --interval 5m --backfill
    python -m goldlab ledger grade --interval 5m
    python -m goldlab ledger report --interval 5m

Nothing here touches the database unless ``--db`` is given and DATABASE_URL is
set; without it everything reads and writes the local cache directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from .contracts import CONTRACTS, GOLD_FUTURES
from .data import load_bars
from .live import load_study, save_study
from .study import DEFAULT_HORIZONS

bars_app = typer.Typer(help="The persistent bar store: history beyond Yahoo's 60 days of 5m.", no_args_is_help=True)
ledger_app = typer.Typer(help="Signal ledger: scan point-in-time, grade as bars arrive, report.", no_args_is_help=True)
console = Console()


def parse_horizons(raw: str) -> tuple[int, ...]:
    values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    return tuple(value for value in values if value > 0) or DEFAULT_HORIZONS


def _split(raw: str) -> list[str]:
    return [name.strip() for name in raw.split(",") if name.strip()]


def open_repo(db: bool):
    """The database repository, only when asked for and configured. Never implicit."""

    if not db:
        return None
    from tradingagents.storage import StorageRepository, create_storage_engine

    if not os.getenv("DATABASE_URL"):
        raise typer.BadParameter("--db requires DATABASE_URL")
    return StorageRepository(create_storage_engine())


def history(symbol: str, interval: str, repo):
    """Stored history (file and database) when there is any, else the cached or fetched bars."""

    from .barstore import load_history

    stored = load_history(symbol, interval, repo=repo)
    return stored if stored and len(stored) else load_bars(symbol, interval=interval)


def walkforward_study(series, symbol, interval, horizons, min_occurrences, window, repo, output) -> None:
    from .ledger import ledger_line, ledger_summary, open_ledger
    from .walkforward import run_walkforward_study

    spec = CONTRACTS.get(symbol, GOLD_FUTURES)
    study = run_walkforward_study(series, horizons=parse_horizons(horizons), min_occurrences=min_occurrences, contract=spec, window_bars=window)
    try:
        summary = ledger_summary(open_ledger(symbol, interval, repo=repo).all())
    except Exception:
        summary = None
    if summary:
        study["ledger"] = summary
        study["ledger_line"] = ledger_line(summary)
    console.print(
        f"[bold]{symbol} {interval}[/bold] 워크포워드({study['window']}) · {study['bars']}봉 · 신호 {study['signals']}건 · "
        f"{study['start'][:16]} → {study['end'][:16]}"
    )
    console.print(f"[dim]거짓 발견율 검사(q={study['fdr']['q']}): {study['fdr']['tested']}칸 중 {study['fdr']['survivors']}칸만 통과[/dim]")
    for horizon in study["horizons"]:
        table = Table(box=box.SIMPLE_HEAD, title=f"{horizon}봉 뒤 (수축 적용)")
        for column in ("패턴", "방향", "표본", "원승률", "수축승률", "기준", "수축 엣지", "FDR", "신뢰도"):
            table.add_column(column)
        rows = 0
        for row in study["patterns"]:
            stats = row["horizons"].get(str(horizon)) or {}
            if not stats.get("enough_samples"):
                continue
            rows += 1
            table.add_row(
                row["label"], "상승" if row["direction"] == "bullish" else "하락", str(stats["count"]),
                f"{stats['win_rate']:.1%}", f"{stats.get('shrunk_win_rate', 0):.1%}", f"{stats.get('base_win_rate', 0):.1%}",
                f"{stats.get('shrunk_edge_win_rate', 0):+.1%}", "통과" if stats.get("fdr_significant") else "-", stats.get("confidence", "-"),
            )
        console.print(table if rows else f"[yellow]{horizon}봉: 표본 {min_occurrences}회를 넘긴 패턴이 없습니다.[/yellow]")
    for note in study["notes"]:
        console.print(f"[yellow]{note}[/yellow]")
    stored = save_study(study, symbol=symbol, interval=interval)
    console.print(f"[dim]measurement stored at {stored}[/dim]")
    if output is not None:
        output.write_text(json.dumps(study, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[dim]saved {output}[/dim]")


@bars_app.command("sync")
def bars_sync_command(
    symbol: str = typer.Option("GC=F", "--symbol", help="GC=F, NQ=F, ..."),
    intervals: str = typer.Option("5m", "--intervals"),
    db: bool = typer.Option(False, "--db", help="Also keep the bars in the database (needs DATABASE_URL)."),
):
    """Fetch what Yahoo serves and merge it into the stored history. Bars are only ever added."""

    from .barstore import sync_bars

    repo = open_repo(db)
    for interval in _split(intervals):
        report = sync_bars(symbol, interval, repo=repo)
        console.print(
            f"[green]{symbol} {interval}[/green] 받은 {report.fetched} · 추가 {report.added} · 갱신 {report.refreshed} · "
            f"전체 {report.total} ({(report.first or '')[:10]} → {(report.last or '')[:16]}) · DB {report.db}"
        )
        for note in report.notes:
            console.print(f"[yellow]{note}[/yellow]")


@bars_app.command("import")
def bars_import_command(
    path: Path = typer.Argument(..., help="OHLCV CSV (timestamp/ts_event, open, high, low, close, volume)."),
    symbol: str = typer.Option(..., "--symbol"),
    interval: str = typer.Option("5m", "--interval"),
    source: str = typer.Option(..., "--source", help="Vendor tag, e.g. databento. Not 'yahoo'."),
    from_interval: Optional[str] = typer.Option(None, "--from-interval", help="Resample from this finer interval, e.g. 1m."),
    raw_symbol: Optional[str] = typer.Option(None, "--raw-symbol", help="Keep only this raw symbol when the file mixes several."),
    db: bool = typer.Option(False, "--db"),
):
    """One-time bulk import. Vendor bars replace Yahoo's for the same time; Yahoo can never replace them."""

    from .barstore import import_bars

    report = import_bars(path, symbol, interval, source=source, from_interval=from_interval, raw_symbol=raw_symbol, repo=open_repo(db))
    console.print(f"[green]{symbol} {interval}[/green] 읽은 {report.fetched} · 추가 {report.added} · 교체 {report.refreshed} · 전체 {report.total} · 출처 {report.sources}")
    for note in report.notes:
        console.print(f"[yellow]{note}[/yellow]")


@ledger_app.command("scan")
def ledger_scan_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    interval: str = typer.Option("5m", "--interval"),
    backfill: bool = typer.Option(False, "--backfill", help="Scan every stored bar (claims computed walk-forward as of each bar)."),
    last: int = typer.Option(800, "--last", min=10, help="Live pass over this many recent bars (claims quoted from the stored study)."),
    db: bool = typer.Option(False, "--db"),
):
    """Record new signals, judged only on the bars up to each one."""

    from .ledger import open_ledger, scan_into_ledger

    repo = open_repo(db)
    series = history(symbol, interval, repo)
    study = load_study(symbol, interval)
    if repo is not None and not study:
        from tradingagents.site.gold_page import load_stored_study

        study = load_stored_study(repo, symbol, interval)
    result = scan_into_ledger(series, open_ledger(symbol, interval, repo=repo), last_bars=None if backfill else last, study=study)
    console.print(f"[green]{symbol} {interval}[/green] {result['origin']} · 훑은 봉 {result['scanned_bars']} · 신호 {result['found']} · 새로 기록 {result['added']}")


@ledger_app.command("grade")
def ledger_grade_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    interval: str = typer.Option("5m", "--interval"),
    horizons: str = typer.Option("4,12,24,72", "--horizons"),
    db: bool = typer.Option(False, "--db"),
):
    """Fill in the grades whose horizon has finished. Existing grades are never touched."""

    from .ledger import grade_ledger, open_ledger

    repo = open_repo(db)
    result = grade_ledger(history(symbol, interval, repo), open_ledger(symbol, interval, repo=repo), horizons=parse_horizons(horizons))
    console.print(f"[green]{symbol} {interval}[/green] 대기 {result['pending']}건 중 채점 {result['graded']}건")


@ledger_app.command("report")
def ledger_report_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    interval: str = typer.Option("5m", "--interval"),
    horizons: str = typer.Option("4,12,24,72", "--horizons"),
    db: bool = typer.Option(False, "--db"),
    output: Optional[Path] = typer.Option(None, "--output", help="Write the report JSON here."),
):
    """Realised record against what the study claimed, per pattern and per context."""

    from .ledger import build_report, open_ledger

    signals = open_ledger(symbol, interval, repo=open_repo(db)).all()
    hs = parse_horizons(horizons)
    report = build_report(signals, horizons=hs)
    console.print(f"[bold]{symbol} {interval}[/bold] 신호 {report['signals']}건 · 출처 {report['origins']}")
    for horizon in hs:
        key = str(horizon)
        overall = report["overall"][key]
        if not overall["n"]:
            console.print(f"[yellow]{horizon}봉: 채점된 신호 없음[/yellow]")
            continue
        claimed = (
            f" · 당시 주장 {overall['claimed_win_rate']:.1%} (n={overall['n_claimed']}) → 차이 {overall['calibration_gap']:+.1%}"
            if "claimed_win_rate" in overall
            else " · 주장 없음"
        )
        console.print(f"[bold]{horizon}봉[/bold] 전체 n={overall['n']} 적중 {overall['hit_rate']:.1%} (95% {overall['hit_rate_ci']}) · 평균 {overall['mean_return']:+.4%}{claimed}")
        table = Table(box=box.SIMPLE_HEAD, title=f"{horizon}봉 · 패턴별 (표본 {report['min_samples']} 이상)")
        for column in ("패턴", "n", "적중", "주장", "주장n", "차이", "목표먼저", "손절먼저"):
            table.add_column(column)
        rows = 0
        for name, by_h in sorted(report["by_pattern"].items(), key=lambda kv: -kv[1][key]["n"]):
            b = by_h[key]
            if b["n"] < report["min_samples"]:
                continue
            rows += 1
            table.add_row(
                name, str(b["n"]), f"{b['hit_rate']:.1%}",
                f"{b['claimed_win_rate']:.1%}" if "claimed_win_rate" in b else "-",
                str(b.get("n_claimed", 0)),
                f"{b['calibration_gap']:+.1%}" if "calibration_gap" in b else "-",
                f"{b.get('target_first', 0):.0%}", f"{b.get('stop_first', 0):.0%}",
            )
        if rows:
            console.print(table)
    for note in report["notes"]:
        console.print(f"[yellow]{note}[/yellow]")
    if output is not None:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[dim]saved {output}[/dim]")
