# DeepSeek Cursor Proxy 启动脚本 (Windows)
# 推荐: 双击或在 cmd 中执行 start-proxy.bat（不受 PowerShell 执行策略限制）
# 若必须用 ps1: powershell -ExecutionPolicy Bypass -File .\start-proxy.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== DeepSeek Cursor Proxy ===" -ForegroundColor Cyan

# 确保 ngrok 在 PATH 中（winget 安装后可能需要新开终端）
$ngrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue
if (-not $ngrokCmd) {
    $candidates = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ngrok.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) {
            $env:Path = "$(Split-Path $p);$env:Path"
            break
        }
    }
}

if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    Write-Host "未找到 ngrok。请先安装并配置 authtoken:" -ForegroundColor Yellow
    Write-Host "  winget install Ngrok.Ngrok"
    Write-Host "  ngrok config add-authtoken <你的-token>"
    Write-Host "详见: https://dashboard.ngrok.com/get-started/your-authtoken"
    exit 1
}

$configDir = Join-Path $env:USERPROFILE ".deepseek-cursor-proxy"
$configFile = Join-Path $configDir "config.yaml"
if (-not (Test-Path $configFile)) {
    Write-Host "正在创建默认配置文件: $configFile"
    python -c "from deepseek_cursor_proxy.config import populate_default_config_file, default_config_path; populate_default_config_file(default_config_path())"
}

Write-Host ""
Write-Host "配置文件: $configFile"
Write-Host "启动代理（含 ngrok 隧道）..."
Write-Host "启动后请将终端里打印的 HTTPS 地址填入 Cursor -> Base URL（末尾加 /v1）"
Write-Host "按 Ctrl+C 停止"
Write-Host ""

deepseek-cursor-proxy
