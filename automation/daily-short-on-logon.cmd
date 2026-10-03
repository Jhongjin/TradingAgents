@echo off
rem Run today's short again after this PC restarts.
rem
rem The 08:40 run is killed whenever the PC restarts mid-render: 09-22, 09-23,
rem 09-30 and 10-02 were all restarted between 08:34 and 08:47. The schedule
rem stays as it is; this only puts a run back once someone logs in again.
rem
rem It runs only on weekdays between 08:40 and 16:00. Before 08:40 the normal
rem trigger is still to come, and an evening or weekend restart must not post
rem a video. Everything else is shorts-daily's job: it exits at once when today
rem is already published, continues the day's chosen story, and refuses to
rem start while another attempt still holds the run lock.
rem
rem Registered as "AgentTrust Daily Short on logon" (at logon, 2 minute delay):
rem   powershell -NoProfile -File D:\Codex\TradingAgents\automation\register-short-on-logon.ps1

setlocal
set REPO=D:\Codex\TradingAgents
set GATE=skip
for /f %%i in ('powershell -NoProfile -Command "$n = Get-Date; $d = [int]$n.DayOfWeek; $t = $n.TimeOfDay; if ($d -ge 1 -and $d -le 5 -and $t -ge [TimeSpan]'08:40' -and $t -lt [TimeSpan]'16:00') { 'run' } else { 'skip' }"') do set GATE=%%i

if not exist "%REPO%\logs" mkdir "%REPO%\logs"
set STAMP=%DATE:~0,10%
set LOG=%REPO%\logs\daily-short-%STAMP:/=-%.log

if /i not "%GATE%"=="run" (
  echo ==== %DATE% %TIME% ==== logon: outside weekday 08:40-16:00, nothing to do >> "%LOG%"
  exit /b 0
)
echo ==== %DATE% %TIME% ==== logon: restarted, attempting today's short >> "%LOG%"
call "%REPO%\automation\daily-short.cmd"
exit /b %ERRORLEVEL%
