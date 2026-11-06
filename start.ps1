# ua-mini 一键启动脚本（PowerShell）
# 用法：右键“使用 PowerShell 运行”，或在本目录执行 .\start.ps1
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. 检查 Python
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) {
    Write-Host "[错误] 未找到 python，请先安装 Python 3.10+" -ForegroundColor Red
    Read-Host "按回车退出"; exit 1
}

# 2. 安装依赖（首次运行）
Push-Location $root
try {
    python -c "import fastapi, uvicorn, sqlalchemy" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[1/2] 安装依赖 fastapi/uvicorn/sqlalchemy ..." -ForegroundColor Yellow
        python -m pip install -r requirements.txt
    } else {
        Write-Host "[1/2] 依赖已就绪" -ForegroundColor Green
    }

    # 3. 启动后端（8765 端口，避免与 UAtool 的 8888 冲突）
    Write-Host "[2/2] 启动服务：http://127.0.0.1:8765" -ForegroundColor Green
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
} finally {
    Pop-Location
}
