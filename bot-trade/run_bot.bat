@echo off
chcp 65001 >nul
title Binance Futures Long/Short Tracker Bot v2.0.3 (MT5 Dashboard)
echo ===============================================================
echo   ⚡ KHOI DONG BINANCE FUTURES LONG/SHORT TRACKER BOT v2.0.3
echo ===============================================================
cd /d "%~dp0"

echo [1/2] Kiem tra thu vien Python...
python -m pip install -r requirements.txt --quiet

echo [2/2] Khoi dong MT5 Web Dashboard tai http://localhost:8000 ...
start "" http://localhost:8000
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
pause

