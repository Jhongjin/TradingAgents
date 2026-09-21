@echo off
rem Intraday stop-loss pass.
rem
rem Why this exists: /api/cron/run-harness runs at 16:40 KST, after the close,
rem so a position that broke its 5% stop during the session was not noticed
rem until the market had shut and was sold the next day. Across the first ten
rem stops the rule said 5% and the book realised 8.81% on average, worst 15.60%
rem — 1,298,162원 more than the rule asked for, 61% over.
rem
rem Why it runs here and not on Vercel: the only intraday price source wired up
rem is NH, and NH's key can place orders. It stays on this machine.
rem
rem Register it (run once, elevated), 09:40 / 11:00 / 12:30 / 14:00 / 15:20 KST:
rem
rem   $times = '09:40','11:00','12:30','14:00','15:20'
rem   $i = 0
rem   foreach ($t in $times) {
rem     $i++
rem     $a = New-ScheduledTaskAction -Execute 'D:\Codex\TradingAgents\automation\intraday-exits.cmd'
rem     $g = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $t
rem     $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
rem            -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
rem            -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
rem     Register-ScheduledTask -TaskName "AgentTrust intraday exits $i" -Action $a -Trigger $g -Settings $s
rem   }
rem
rem StartWhenAvailable and WakeToRun matter: a missed 08:40 is why a Friday
rem video never got made.

rem Delayed expansion: inside a for block %ERRORLEVEL% is expanded once when
rem the block is parsed, so it printed literally and hid the exit code.
setlocal enabledelayedexpansion
set REPO=D:\Codex\TradingAgents
set PYTHON=%REPO%\.codex-test-venv\Scripts\python.exe

cd /d "%REPO%" || exit /b 1
if not exist "%REPO%\logs" mkdir "%REPO%\logs"
set STAMP=%DATE:~0,10%
set LOG=%REPO%\logs\intraday-exits-%STAMP:/=-%.log

echo ==== %DATE% %TIME% ==== >> "%LOG%"

rem All three books get the same treatment: the comparison between them is only
rem meaningful if the exit rule runs identically on each.
rem
rem kis was missing here and it showed. SK이노베이션 sat at -10.52% against a
rem 142,383 stop with nothing looking at it, because every executed run on
rem record was broker=paper.
for %%A in (paper rules) do (
  echo ---- account %%A >> "%LOG%"
  "%PYTHON%" -m cli.main pipeline ^
    --exits-only --execute --persist --broker paper --account %%A ^
    --confirmer none >> "%LOG%" 2>&1
  if errorlevel 1 echo [warn] account %%A exited !ERRORLEVEL! >> "%LOG%"
)

echo ---- account kis >> "%LOG%"
"%PYTHON%" -m cli.main pipeline ^
  --exits-only --execute --persist --broker kis --account kis ^
  --confirmer none >> "%LOG%" 2>&1
if errorlevel 1 echo [warn] account kis exited !ERRORLEVEL! >> "%LOG%"

rem Straight after the fill. The notify-exits cron runs once, at 10:35, so a
rem stop that fires at 14:00 would have waited until 10:35 tomorrow — by which
rem point it is not news, and the subscriber has watched it happen without
rem hearing from us.
echo ---- notify >> "%LOG%"
"%PYTHON%" -m cli.main notify --what exits >> "%LOG%" 2>&1
if errorlevel 1 echo [warn] notify exited !ERRORLEVEL! >> "%LOG%"

endlocal
