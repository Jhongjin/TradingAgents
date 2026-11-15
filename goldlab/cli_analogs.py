"""Similar past charts from the command line.

    python -m goldlab analogs refresh --symbol GC=F --interval 5m --db
    python -m goldlab analogs validate --symbol GC=F --interval 5m --output result.json

``refresh`` reads the file store (set GOLDLAB_CACHE_DIR), finds the analogs of the
newest window and, with ``--db``, replaces the one stored row the page reads.
``validate`` is the slow honesty check (minutes) whose result the card quotes.
Research only; nothing here places an order.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .cli_ledger import open_repo

analogs_app = typer.Typer(help="Similar past charts: nearest-neighbour search and its walk-forward check.", no_args_is_help=True)
console = Console()


def _names(interval: Optional[str], intervals: Optional[str]) -> list[str]:
    raw = intervals or interval or "5m"
    return [part.strip() for part in raw.split(",") if part.strip()]


@analogs_app.command("refresh")
def refresh_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    interval: Optional[str] = typer.Option(None, "--interval"),
    intervals: Optional[str] = typer.Option(None, "--intervals", help="Comma list, e.g. 5m,1h."),
    db: bool = typer.Option(False, "--db", help="Store the result for the page (needs DATABASE_URL)."),
):
    """Compute the current analogs from the file store and store them."""

    from .analogs import refresh

    repo = open_repo(db)
    for name in _names(interval, intervals):
        started = time.perf_counter()
        payload = refresh(symbol, name, repo=repo)
        seconds = time.perf_counter() - started
        found = len(payload["analogs"])
        stored = "DB 저장" if repo is not None else "저장 안 함"
        console.print(f"[green]{symbol} {name}[/green] 닮은 구간 {found}곳 · 기준 봉 {payload['last_bar'][:16]} · {stored} · {seconds:.1f}초")


@analogs_app.command("validate")
def validate_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    interval: str = typer.Option("5m", "--interval"),
    queries: int = typer.Option(3000, "--queries", min=100),
    output: Optional[Path] = typer.Option(None, "--output", help="Also write the JSON here."),
):
    """Walk-forward check over the whole stored history; saved next to the bars for ``refresh``."""

    from .analogs import load_arrays, validate, validation_path

    started = time.perf_counter()
    arrays = load_arrays(symbol, interval)
    result = validate(arrays, queries=queries, progress=lambda text: console.print(f"[dim]{text}[/dim]"))
    result["seconds"] = round(time.perf_counter() - started, 1)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    validation_path(symbol, interval).write_text(text, encoding="utf-8")
    if output is not None:
        output.write_text(text, encoding="utf-8")
    console.print(f"[bold]{symbol} {interval}[/bold] {result['line']} ({result['seconds']}초)")
