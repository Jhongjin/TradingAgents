"""The daily review note from the command line.

    python -m goldlab review run --symbol GC=F --db
    python -m goldlab review run --symbol GC=F --db --date 2026-11-14 --force
    python -m goldlab review hypotheses --symbol GC=F --db --if-due
    python -m goldlab review show --symbol GC=F --db

``run`` is safe to call every two hours: it writes one note per KST trading day and
does nothing when that day's note exists. A provider failure is reported, never raised.
Research only; nothing here places an order.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import typer
from rich.console import Console

from .cli_ledger import open_repo

review_app = typer.Typer(help="AI 복기 노트: three-model debate over a code-built evidence pack.", no_args_is_help=True)
console = Console()


@review_app.command("run")
def run_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    db: bool = typer.Option(False, "--db", help="Read and store in the database (needs DATABASE_URL)."),
    day: Optional[str] = typer.Option(None, "--date", help="Review day (KST, YYYY-MM-DD); default is the newest trading day."),
    force: bool = typer.Option(False, "--force", help="Write again even if the note exists."),
    max_usd: Optional[float] = typer.Option(None, "--max-usd", help="Daily cap across both symbols; default GOLDLAB_REVIEW_MAX_USD or 0.60."),
):
    """Write the note for the newest finished trading day, once."""

    from .review import run_review

    repo = open_repo(db)
    if repo is None:
        raise typer.BadParameter("review needs the database (--db): notes are stored in backtest_runs")
    try:
        result = run_review(symbol, repo=repo, day=date.fromisoformat(day) if day else None, force=force, max_usd=max_usd, now=datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 - the scheduled sync must carry on
        console.print(f"[red]{symbol} review failed: {exc.__class__.__name__}: {str(exc)[:200]}[/red]")
        return
    detail = " ".join(f"{k}={v}" for k, v in result.items() if k != "symbol")
    console.print(f"[green]{symbol} review[/green] {detail}")


@review_app.command("hypotheses")
def hypotheses_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    db: bool = typer.Option(False, "--db"),
    if_due: bool = typer.Option(False, "--if-due", help="Skip unless a week has passed since the last run."),
):
    """Run the critic's untested hypotheses through the walk-forward study (weekly, slow)."""

    from .review import run_weekly_hypotheses

    repo = open_repo(db)
    if repo is None:
        raise typer.BadParameter("hypotheses needs the database (--db)")
    try:
        result = run_weekly_hypotheses(symbol, repo=repo, if_due=if_due)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]{symbol} hypotheses failed: {exc.__class__.__name__}: {str(exc)[:200]}[/red]")
        return
    console.print(f"[green]{symbol} hypotheses[/green] " + " ".join(f"{k}={v}" for k, v in result.items() if k != "symbol"))


@review_app.command("show")
def show_command(
    symbol: str = typer.Option("GC=F", "--symbol"),
    db: bool = typer.Option(False, "--db"),
    day: Optional[str] = typer.Option(None, "--date"),
):
    """Print the stored note."""

    from .review import list_records, load_record

    repo = open_repo(db)
    if repo is None:
        raise typer.BadParameter("show needs the database (--db)")
    record = load_record(repo, symbol, day) if day else next((r for r in list_records(repo, symbol, limit=6) if r.get("status") == "ok"), None)
    if not record:
        console.print("[yellow]no note stored[/yellow]")
        return
    console.print(record.get("text") or record)
    usage = record.get("usage") or {}
    console.print(f"[dim]cost ${usage.get('cost_usd')} · tokens in {usage.get('input_tokens')} out {usage.get('output_tokens')} · removed {len((record.get('guard') or {}).get('removed') or [])}[/dim]")
