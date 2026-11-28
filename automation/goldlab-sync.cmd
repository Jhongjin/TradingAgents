@echo off
rem Keep gold and Nasdaq futures bars past Yahoo's window, and grade the lab's signals.
rem
rem GitHub Actions has been disabled on this repository since 2026-10-14, so the
rem two-hourly job in .github/workflows/goldlab-study.yml does not run. This does
rem the same work from this machine. Yahoo serves 1-minute bars for only 7 days,
rem so a week with this machine off leaves a hole in the 1-minute history.
rem
rem 1m stays in the file store only (ten years of it would not fit the free
rem database); 5m and 1h also go to the database the chart reads.
rem
rem The steps live in goldlab_sync.py: each runs as its own subprocess with a
rem timeout (the whole process tree is killed), failures are logged and skipped,
rem and a lock file lets a new run replace one that hung (see that file).
rem
rem Register (every 2 hours, every day):
rem   schtasks /create /tn "AgentTrust goldlab sync" /tr "D:\Codex\TradingAgents\automation\goldlab-sync.cmd" /sc hourly /mo 2 /st 00:10 /f

setlocal
set REPO=D:\Codex\TradingAgents
set PYTHON=%REPO%\.codex-test-venv\Scripts\python.exe
set GOLDLAB_CACHE_DIR=D:\Codex\goldlab-store
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
rem AI review note: hard daily cap in USD across both symbols (models: GOLDLAB_REVIEW_ANALYST / _CRITIC / _VERIFIER).
if not defined GOLDLAB_REVIEW_MAX_USD set GOLDLAB_REVIEW_MAX_USD=0.60

cd /d "%REPO%" || exit /b 1
if not exist "%REPO%\logs" mkdir "%REPO%\logs"
rem Output goes to a file, never to the console window. A click inside that window
rem (QuickEdit selection) pauses console writes, and the 11-27 22:36 run froze on a
rem print for 14 hours; the task then skipped every trigger because it was "running".
"%PYTHON%" "%REPO%\automation\goldlab_sync.py" --symbols "GC=F,NQ=F" >> "%REPO%\logs\goldlab-sync-console.log" 2>&1
exit /b 0
