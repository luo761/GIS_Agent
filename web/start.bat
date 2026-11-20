@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
chcp 65001 >nul 2>nul

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 python 命令。
  echo 请先安装 Python 3.10+ 并加入 PATH，或在命令行执行：
  echo     python web\server\app.py --open
  pause
  exit /b 1
)

echo ============================================================
echo   GIS 多智能体 Web 控制台
echo   浏览器将自动打开 http://127.0.0.1:8765
echo   关闭本窗口即停止服务
echo ============================================================
python server\app.py --open %*
if errorlevel 1 (
  echo.
  echo [服务已退出] 如果提示端口占用，可尝试：
  echo     python server\app.py --port 8766 --open
  pause
)
endlocal
