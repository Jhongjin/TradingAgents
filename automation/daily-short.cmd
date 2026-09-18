@echo off
rem Make today's short on this machine and hand it to n8n to publish.
rem
rem The render needs this PC: its GPU draws the frames and its local VoxCPM
rem speaks the lines. So the work runs here and the finished file is pushed out
rem to the hosted n8n, which means nothing has to reach in through the firewall.
rem
rem Register with Task Scheduler (weekdays 08:40 KST):
rem   schtasks /create /tn "AgentTrust Daily Short" /tr "D:\Codex\TradingAgents\automation\daily-short.cmd" /sc weekly /d MON,TUE,WED,THU,FRI /st 08:40 /rl highest /f
rem
rem schtasks cannot set these three, and without them a morning is simply lost.
rem 2026-09-18: the PC booted at 08:36:59 and the scheduler had not picked the
rem 08:40 trigger up in time; the run was skipped and the next one moved to
rem Monday, so Friday had no video and nothing said so. Run this straight after
rem the create above:
rem
rem   powershell -NoProfile -Command "$t = Get-ScheduledTask -TaskName 'AgentTrust Daily Short'; $t.Settings.StartWhenAvailable = $true; $t.Settings.WakeToRun = $true; $t.Settings.DisallowStartIfOnBatteries = $false; $t.Settings.StopIfGoingOnBatteries = $false; Set-ScheduledTask -TaskName 'AgentTrust Daily Short' -Settings $t.Settings"
rem
rem   StartWhenAvailable  - a missed 08:40 runs as soon as the machine is back
rem   WakeToRun           - a sleeping machine wakes for it
rem   DisallowStartIfOnBatteries - off, or a laptop on battery never publishes
rem
rem Remove it again:
rem   schtasks /delete /tn "AgentTrust Daily Short" /f

setlocal
set REPO=D:\Codex\TradingAgents
set PYTHON=%REPO%\.codex-test-venv\Scripts\python.exe

rem The webhook address is not a secret, so it lives here. The shared secret is,
rem and this file is in version control, so it is never written here: set it once
rem as a user environment variable and it arrives on its own.
rem
rem   setx TRADINGAGENTS_SHORTS_WEBHOOK_TOKEN "the same value as n8n's X-Shorts-Token"
rem
set TRADINGAGENTS_SHORTS_WEBHOOK=https://n8n.admate.ai.kr/webhook/agenttrust-short

if not defined TRADINGAGENTS_SHORTS_WEBHOOK_TOKEN (
  echo TRADINGAGENTS_SHORTS_WEBHOOK_TOKEN is not set - n8n would answer 403. 1>&2
  exit /b 2
)

cd /d "%REPO%" || exit /b 1

if not exist "%REPO%\logs" mkdir "%REPO%\logs"
set STAMP=%DATE:~0,10%
set LOG=%REPO%\logs\daily-short-%STAMP:/=-%.log

echo ==== %DATE% %TIME% ==== >> "%LOG%"
rem Goes out public. Change to private to have a look before anyone else does.
"%PYTHON%" -m cli.main shorts-daily --privacy public >> "%LOG%" 2>&1
set CODE=%ERRORLEVEL%
echo exit=%CODE% >> "%LOG%"

exit /b %CODE%
