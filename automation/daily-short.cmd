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
rem Remove it again:
rem   schtasks /delete /tn "AgentTrust Daily Short" /f

setlocal
set REPO=D:\Codex\TradingAgents
set PYTHON=%REPO%\.codex-test-venv\Scripts\python.exe

rem The webhook and its shared secret. Fill these in, or set them as user
rem environment variables and delete these two lines.
set TRADINGAGENTS_SHORTS_WEBHOOK=https://n8n.admate.ai.kr/webhook/agenttrust-short
set TRADINGAGENTS_SHORTS_WEBHOOK_TOKEN=

cd /d "%REPO%" || exit /b 1

if not exist "%REPO%\logs" mkdir "%REPO%\logs"
set STAMP=%DATE:~0,10%
set LOG=%REPO%\logs\daily-short-%STAMP:/=-%.log

echo ==== %DATE% %TIME% ==== >> "%LOG%"
"%PYTHON%" -m cli.main shorts-daily --privacy private >> "%LOG%" 2>&1
set CODE=%ERRORLEVEL%
echo exit=%CODE% >> "%LOG%"

exit /b %CODE%
