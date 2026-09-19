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

setlocal
set REPO=D:\Codex\TradingAgents
set PYTHON=%REPO%\.codex-test-venv\Scripts\python.exe

cd /d "%REPO%" || exit /b 1
if not exist "%REPO%\logs" mkdir "%REPO%\logs"
set STAMP=%DATE:~0,10%
set LOG=%REPO%\logs\intraday-exits-%STAMP:/=-%.log

echo ==== %DATE% %TIME% ==== >> "%LOG%"

rem Both books get the same treatment: the comparison between them is only
rem meaningful if the exit rule runs identically on each.
for %%A in (paper rules) do (
  echo ---- account %%A >> "%LOG%"
  "%PYTHON%" -m cli.main pipeline ^
    --exits-only --execute --persist --broker paper --account %%A ^
    --confirmer none >> "%LOG%" 2>&1
  if errorlevel 1 echo [warn] account %%A exited %%ERRORLEVEL%% >> "%LOG%"
)

endlocal
