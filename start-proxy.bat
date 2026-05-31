@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

cd /d "%~dp0"
title DeepSeek Cursor Proxy

echo === DeepSeek Cursor Proxy ===
echo.

set "PY_SCRIPTS=%LOCALAPPDATA%\Programs\Python\Python312\Scripts"
if exist "%PY_SCRIPTS%" set "PATH=%PY_SCRIPTS%;%PATH%"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+
    goto fail
)

set "PROXY_CMD="
where deepseek-cursor-proxy >nul 2>&1
if not errorlevel 1 (
    set "PROXY_CMD=deepseek-cursor-proxy"
) else (
    python -c "import deepseek_cursor_proxy" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Package not installed. Run: pip install -e .
        goto fail
    )
    set "PROXY_CMD=python -m deepseek_cursor_proxy"
)

where ngrok >nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ngrok.exe" (
        set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
    ) else if exist "%LOCALAPPDATA%\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe" (
        set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe;%PATH%"
    )
)

where ngrok >nul 2>&1
if errorlevel 1 (
    echo [ERROR] ngrok not found.
    echo Install: winget install Ngrok.Ngrok
    echo Then run: ngrok config add-authtoken YOUR_TOKEN
    echo Get token: https://dashboard.ngrok.com/get-started/your-authtoken
    goto fail
)

set "CONFIG_FILE=%USERPROFILE%\.deepseek-cursor-proxy\config.yaml"
if not exist "%CONFIG_FILE%" (
    echo Creating default config...
    python -c "from deepseek_cursor_proxy.config import populate_default_config_file, default_config_path; populate_default_config_file(default_config_path())"
    if errorlevel 1 goto fail
)

echo Config file: %CONFIG_FILE%
echo Command: !PROXY_CMD!
echo.
echo Copy the HTTPS URL below into Cursor - Base URL (add /v1 at the end)
echo Press Ctrl+C in this window to stop
echo ----------------------------------------
echo.

!PROXY_CMD!
set "EXIT_CODE=!ERRORLEVEL!"

if !EXIT_CODE! neq 0 (
    echo.
    echo [Proxy exited with code !EXIT_CODE!]
    echo.
    echo If you see "ngrok exited before creating a tunnel", try:
    echo   ngrok update
    echo Then run this script again.
    goto fail
)

exit /b 0

:fail
echo.
echo Press any key to close...
pause >nul
exit /b 1
