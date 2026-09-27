@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3 is required. Install it from python.org, then run this file again.
  pause
  exit /b 1
)
echo Open http://127.0.0.1:8787 in your browser.
echo Keep this window open while using MandateScout. Press Ctrl+C to stop.
python product\server.py
pause
