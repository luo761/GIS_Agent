@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul 2>nul
set PYTHONIOENCODING=utf-8

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] python not found in PATH.
  echo Install Python 3.10+ or run:
  echo     python web\server\app.py --open
  pause
  exit /b 1
)

echo ============================================================
echo   GIS Multi-Agent Web Console
echo   Browser: http://127.0.0.1:8765
echo   Close this window to stop the server.
echo ============================================================
python server\app.py --open %*
if errorlevel 1 (
  echo.
  echo [Server exited] If the port is busy, try:
  echo     python server\app.py --port 8766 --open
  pause
)
endlocal
