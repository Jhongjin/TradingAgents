"""Two-hourly gold lab sync, one subprocess per step, every step on a clock.

The scheduled task used to be a cmd file that ran seven commands per symbol in a
row. A step that never returned (11-19: inside the review, 11-21: between two
bar syncs) froze the whole run, and because the task refuses a second instance
while one is running, every later trigger that day was skipped silently.

This runner:

* gives every step its own timeout and kills the step's whole process tree
  (taskkill /T) when it is exceeded, because ``opencode`` and ``npm`` shims leave
  a grandchild holding the pipes;
* logs start, end, exit code and duration of every step, then goes on with the
  next one, so one bad step costs one step;
* keeps a lock file (PID + start time). A newer run that finds a live run older
  than STALE_MINUTES kills it and takes over; a run younger than that is left
  alone and the newer one exits;
* stops starting steps once DEADLINE_MINUTES have passed, so a run always ends
  before the next two-hourly trigger.

Research only; nothing here places an order.

    python automation/goldlab_sync.py [--symbols "GC=F,NQ=F"] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
RUN = REPO / "automation" / "goldlab_run.py"
LOG_DIR = REPO / "logs"
LOCK = LOG_DIR / "goldlab-sync.lock"

STALE_MINUTES = 90        # a run older than this is presumed hung and is killed by the next one
DEADLINE_MINUTES = 105    # no new step starts after this; keeps one run inside the two-hour cadence
DEFAULT_SYMBOLS = ("GC=F", "NQ=F")


@dataclass(frozen=True)
class Step:
    name: str
    args: tuple[str, ...]      # arguments after goldlab_run.py, {symbol} is substituted
    timeout: int               # seconds


STEPS = (
    Step("bars-1m", ("bars", "sync", "--symbol", "{symbol}", "--intervals", "1m"), 600),
    Step("bars-5m-1h", ("bars", "sync", "--symbol", "{symbol}", "--intervals", "5m,1h", "--db"), 600),
    Step("ledger-scan", ("ledger", "scan", "--symbol", "{symbol}", "--interval", "5m", "--last", "800", "--db"), 600),
    Step("ledger-grade", ("ledger", "grade", "--symbol", "{symbol}", "--interval", "5m", "--db"), 600),
    # 586 s on a busy machine, 52 s on an idle one; the 1776 s and 3003 s runs were starved of CPU
    Step("analogs", ("analogs", "refresh", "--symbol", "{symbol}", "--intervals", "5m,1h", "--db"), 600),
    # one note per KST trading day (the last five days are backfilled), skipped when it exists
    Step("review", ("review", "run", "--symbol", "{symbol}", "--db"), 15 * 60),
    Step("hypotheses", ("review", "hypotheses", "--symbol", "{symbol}", "--db", "--if-due"), 20 * 60),
)


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_path() -> Path:
    return LOG_DIR / f"goldlab-sync-{datetime.now():%Y-%m-%d}.log"


def log(text: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with log_path().open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(text.rstrip("\n") + "\n")
    print(text, flush=True)


# --------------------------------------------------------------------------
# processes (Windows first; the kill fallback keeps it testable elsewhere)
# --------------------------------------------------------------------------
def kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=60)
    else:
        try:
            os.killpg(os.getpgid(pid), 9)
        except OSError:
            try:
                os.kill(pid, 9)
            except OSError:
                pass


def process_start_time(pid: int) -> float | None:
    """Epoch seconds when ``pid`` started, or None when no such process is running."""

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            created, exited, kernel_t, user_t = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_t), ctypes.byref(user_t)):
                return None
            if exited.dwLowDateTime or exited.dwHighDateTime:
                return None
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
            return ticks / 10_000_000 - 11_644_473_600
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return time.time()


# --------------------------------------------------------------------------
# the lock
# --------------------------------------------------------------------------
def read_lock() -> dict | None:
    try:
        return json.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def acquire_lock(now: float | None = None) -> bool:
    """True when this run may go on. Takes over from a dead or stale run."""

    now = now or time.time()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for _attempt in range(3):
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = read_lock() or {}
            pid = int(held.get("pid") or 0)
            started = float(held.get("started") or 0)
            actual = process_start_time(pid) if pid else None
            # same PID but a different start time means the PID was reused by something else
            alive = actual is not None and abs(actual - float(held.get("pid_started") or actual)) < 5
            age_min = (now - started) / 60 if started else float("inf")
            if alive and age_min < STALE_MINUTES:
                log(f"==== {stamp()} 건너뜀: 이전 실행(PID {pid})이 {age_min:.0f}분째 진행 중 ====")
                return False
            if alive:
                log(f"==== {stamp()} 이전 실행(PID {pid})이 {age_min:.0f}분째라 멈춘 것으로 보고 종료 ====")
                kill_tree(pid)
                time.sleep(2)
            else:
                log(f"==== {stamp()} 이전 실행의 잠금 파일이 남아 있어 정리 (PID {pid}) ====")
            try:
                LOCK.unlink()
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started": now, "pid_started": process_start_time(os.getpid()) or now, "host_started": datetime.fromtimestamp(now).isoformat(timespec="seconds")}, handle)
        return True
    return False


def release_lock() -> None:
    held = read_lock()
    if held and int(held.get("pid") or 0) == os.getpid():
        try:
            LOCK.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------
# one step
# --------------------------------------------------------------------------
def run_step(symbol: str, step: Step, *, timeout: float, env: dict[str, str]) -> tuple[str, int | None, float]:
    """Run one step; returns (status, exit code, seconds). Never raises."""

    args = [PYTHON, str(RUN), *(a.format(symbol=symbol) for a in step.args)]
    started = time.monotonic()
    log(f"[{stamp()}] 시작 {symbol} {step.name} (제한 {int(timeout)}초)")
    try:
        with log_path().open("ab") as handle:
            proc = subprocess.Popen(args, cwd=str(REPO), env=env, stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            try:
                code = proc.wait(timeout=timeout)
                status = "ok" if code == 0 else "failed"
            except subprocess.TimeoutExpired:
                kill_tree(proc.pid)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass
                code, status = None, "timeout"
    except Exception as exc:  # noqa: BLE001 - one step must never stop the run
        code, status = None, f"error:{exc.__class__.__name__}"
    seconds = time.monotonic() - started
    log(f"[{stamp()}] 끝 {symbol} {step.name} status={status} exit={code} {seconds:.1f}초")
    return status, code, seconds


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("GOLDLAB_CACHE_DIR", r"D:\Codex\goldlab-store")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("GOLDLAB_REVIEW_MAX_USD", "0.60")   # hard daily cap in USD across both symbols
    # a stalled connection to the remote database must fail the step, not freeze it
    env.setdefault("STORAGE_DB_TIMEOUT_SECONDS", "120")
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--only", default="", help="comma list of step names to run (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    ns = parser.parse_args(argv)
    symbols = [s.strip() for s in ns.symbols.split(",") if s.strip()]
    only = {s.strip() for s in ns.only.split(",") if s.strip()}
    steps = [s for s in STEPS if not only or s.name in only]
    if ns.dry_run:
        for symbol in symbols:
            for step in steps:
                print(symbol, step.name, step.timeout, " ".join(a.format(symbol=symbol) for a in step.args))
        return 0
    if not acquire_lock():
        return 0
    begun = time.monotonic()
    deadline = begun + DEADLINE_MINUTES * 60
    outcomes: list[tuple[str, str, str]] = []
    try:
        log(f"==== {stamp()} 시작 PID {os.getpid()} ====")
        env = child_env()
        for symbol in symbols:
            for step in steps:
                left = deadline - time.monotonic()
                if left < 30:
                    log(f"[{stamp()}] 건너뜀 {symbol} {step.name}: 전체 제한 {DEADLINE_MINUTES}분 도달")
                    outcomes.append((symbol, step.name, "skipped"))
                    continue
                status, _code, _seconds = run_step(symbol, step, timeout=min(step.timeout, left), env=env)
                outcomes.append((symbol, step.name, status))
        bad = [f"{s}/{n}={st}" for s, n, st in outcomes if st != "ok"]
        log(f"==== {stamp()} 끝 {(time.monotonic() - begun) / 60:.1f}분 · 이상 {len(bad)}건" + (": " + ", ".join(bad) if bad else "") + " ====")
    finally:
        release_lock()
    return 0


if __name__ == "__main__":
    sys.exit(main())
