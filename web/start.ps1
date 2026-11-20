# GIS 多智能体 Web 控制台
# 用法：在 PowerShell 中执行 .\start.ps1 [-Port 8765]
param(
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "[错误] 未找到 python 命令，请先安装 Python 3.10+ 并加入 PATH。" -ForegroundColor Red
    exit 1
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  GIS 多智能体 Web 控制台" -ForegroundColor Cyan
Write-Host "  http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host "  按 Ctrl+C 停止服务" -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan

$argsList = @("server/app.py", "--port", "$Port")
if (-not $NoBrowser) { $argsList += "--open" }
& $python.Source @argsList
