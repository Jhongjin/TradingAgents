@echo off
rem The morning pass: screen, decide, and actually fill.
rem
rem Why this exists: /api/cron/run-harness always passes dry_run=True, so the
rem web cron records intent and fills nothing. Every fill in the database up to
rem now came from someone running the CLI by hand — 1 run on the 16th, 9 on the
rem 17th, 8 on the 18th. That is not a record of a system deciding daily; it is
rem a record of when a person was at the keyboard, and the site says "AI가
rem 스스로 판단해서 매수/손절한다".
rem
rem Three books, and they must run the same way every day or the comparison
rem between them means nothing:
rem   paper  AI 확인    - the screen plus an LLM confirmation
rem   rules  규칙 전용  - the same screen, no LLM, as the control
rem   kis    KIS 모의투자 - the same decisions against KIS's own paper server
rem
rem 08:20 KST, before the open and before the 08:40 shorts build, so the video
rem reports the morning that just happened rather than yesterday's.
rem
rem Register it (run once, elevated):
rem
rem   $a = New-ScheduledTaskAction -Execute 'D:\Codex\TradingAgents\automation\daily-harness.cmd'
rem   $g = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 08:20
rem   $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
rem          -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
rem          -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
rem   Register-ScheduledTask -TaskName 'AgentTrust Daily Harness' -Action $a -Trigger $g -Settings $s
rem
rem StartWhenAvailable and WakeToRun are not optional: a missed 08:40 is why a
rem Friday video never got made.

rem Delayed expansion: inside a for block %ERRORLEVEL% is expanded once when
rem the block is parsed, so it printed literally and hid the exit code.
setlocal enabledelayedexpansion
set REPO=D:\Codex\TradingAgents
set PYTHON=%REPO%\.codex-test-venv\Scripts\python.exe

cd /d "%REPO%" || exit /b 1
if not exist "%REPO%\logs" mkdir "%REPO%\logs"
set STAMP=%DATE:~0,10%
set LOG=%REPO%\logs\daily-harness-%STAMP:/=-%.log

echo ==== %DATE% %TIME% ==== >> "%LOG%"

rem The AI-confirmed book. playbook rather than debate: one LLM pass per
rem candidate finishes inside the window, a debate does not reliably.
echo ---- paper (AI 확인) >> "%LOG%"
"%PYTHON%" -m cli.main pipeline --execute --persist ^
  --broker paper --account paper --confirmer playbook >> "%LOG%" 2>&1
if errorlevel 1 echo [warn] paper exited !ERRORLEVEL! >> "%LOG%"

rem The control. Same screen, no LLM — the whole point is that the only
rem difference between this book and the one above is the confirmation step.
echo ---- rules (규칙 전용) >> "%LOG%"
"%PYTHON%" -m cli.main pipeline --execute --persist ^
  --broker paper --account rules --confirmer none >> "%LOG%" 2>&1
if errorlevel 1 echo [warn] rules exited !ERRORLEVEL! >> "%LOG%"

rem KIS's own 모의투자 server. Live trading needs KIS_IS_PAPER=false plus
rem TRADINGAGENTS_ENABLE_LIVE_TRADING and --confirm-live, none of which are
rem here, so this cannot reach real money however it is edited.
echo ---- kis (KIS 모의투자) >> "%LOG%"
"%PYTHON%" -m cli.main pipeline --execute --persist ^
  --broker kis --account kis --confirmer playbook >> "%LOG%" 2>&1
if errorlevel 1 echo [warn] kis exited !ERRORLEVEL! >> "%LOG%"

rem Announce it now rather than waiting for the 07:56 / 10:25 cron slots, which
rem both sit on the wrong side of an 08:20 run: the first fires before it and
rem the second two hours after.
echo ---- notify >> "%LOG%"
"%PYTHON%" -m cli.main notify --what issue >> "%LOG%" 2>&1
if errorlevel 1 echo [warn] notify exited !ERRORLEVEL! >> "%LOG%"

endlocal
