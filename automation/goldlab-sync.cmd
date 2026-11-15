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
rem Register (every 2 hours, every day):
rem   schtasks /create /tn "AgentTrust goldlab sync" /tr "D:\Codex\TradingAgents\automation\goldlab-sync.cmd" /sc hourly /mo 2 /st 00:10 /f

setlocal
set REPO=D:\Codex\TradingAgents
set PYTHON=%REPO%\.codex-test-venv\Scripts\python.exe
set RUN=%REPO%\automation\goldlab_run.py
set GOLDLAB_CACHE_DIR=D:\Codex\goldlab-store
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

cd /d "%REPO%" || exit /b 1
if not exist "%REPO%\logs" mkdir "%REPO%\logs"
set STAMP=%DATE:~0,10%
set LOG=%REPO%\logs\goldlab-sync-%STAMP:/=-%.log

echo ==== %DATE% %TIME% ==== >> "%LOG%"
rem "=" splits a bare for-list in cmd (GC=F becomes GC and F), so the symbols are quoted.
for %%S in ("GC=F" "NQ=F") do (
  "%PYTHON%" "%RUN%" bars sync --symbol %%~S --intervals 1m >> "%LOG%" 2>&1
  "%PYTHON%" "%RUN%" bars sync --symbol %%~S --intervals 5m,1h --db >> "%LOG%" 2>&1
  "%PYTHON%" "%RUN%" ledger scan --symbol %%~S --interval 5m --last 800 --db >> "%LOG%" 2>&1
  "%PYTHON%" "%RUN%" ledger grade --symbol %%~S --interval 5m --db >> "%LOG%" 2>&1
  "%PYTHON%" "%RUN%" analogs refresh --symbol %%~S --intervals 5m,1h --db >> "%LOG%" 2>&1
)
echo exit=%ERRORLEVEL% >> "%LOG%"
exit /b 0
