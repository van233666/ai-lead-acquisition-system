param([switch]$NoOpen)

# ua-mini 一键启动器
#   - 端口已在监听 → 直接打开页面
#   - 没在监听     → 起服务（自动重载）→ 等端口出现 → 打开页面
#   - 不管检测结果如何，最后都会打开页面（检测误报不会挡住你）

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py   = Join-Path $root ".venv\Scripts\python.exe"
$url  = "http://127.0.0.1:8765/"
$port = 8765

function Get-Listener {
    try { Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue } catch { $null }
}

function Open-Page {
    if ($NoOpen) { return }
    try { Start-Process $url }
    catch {
        try { Start-Process "explorer.exe" $url } catch {}
    }
}

Write-Host "==== ua-mini 启动器 ====" -ForegroundColor Cyan

# 1) 已经在跑？只看端口监听表，不发网络请求（避免误判）
$existing = Get-Listener
if ($existing) {
    Write-Host "服务已在运行（端口 $port 已监听），直接打开页面。" -ForegroundColor Green
    Open-Page
    Write-Host "页面：$url" -ForegroundColor Green
    exit 0
}

if (-not (Test-Path -LiteralPath $py)) {
    Write-Host "[错误] 找不到 Python：$py" -ForegroundColor Red
    exit 1
}

# 2) 启动服务：会弹出一个独立的黑窗口（服务窗口）
Write-Host "正在启动服务，约 3 秒…（会弹出一个服务窗口，那个窗口别关，关掉 = 停服务）" -ForegroundColor Yellow
Start-Process -FilePath $py `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8765", "--reload") `
    -WorkingDirectory $root

# 3) 等端口出现（最多 20 秒），只看监听表，不做 HTTP 探测
$deadline = (Get-Date).AddSeconds(20)
$up = $false
while ((Get-Date) -lt $deadline) {
    if (Get-Listener) { $up = $true; break }
    Start-Sleep -Milliseconds 500
}

if ($up) {
    Write-Host "服务已就绪，正在打开页面…" -ForegroundColor Green
} else {
    Write-Host "[提醒] 20 秒内没看到端口 $port 监听，服务可能没起来。" -ForegroundColor Red
    Write-Host "       去看弹出的服务窗口里的报错；页面也可能稍后能打开。" -ForegroundColor DarkGray
}

# 4) 无论检测如何都打开页面
Open-Page
Write-Host "页面地址：$url" -ForegroundColor Green

if (-not $up) { exit 1 }
