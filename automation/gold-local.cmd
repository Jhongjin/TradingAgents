@echo off
rem Double-click: opens the private gold chart at http://127.0.0.1:8765/lab/gold
cd /d "D:\Codex\TradingAgents" || exit /b 1
"D:\Codex\TradingAgents\.codex-test-venv\Scripts\python.exe" "D:\Codex\TradingAgents\automation\gold_local.py" %*
