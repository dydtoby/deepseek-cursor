@echo off
chcp 65001 >nul
title DeepSeek Cursor Proxy 卸载

set "INSTALL_DIR=%LOCALAPPDATA%\Programs\DeepSeekCursorProxy"
set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\DeepSeek Cursor Proxy"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"

echo ================================================
echo   DeepSeek Cursor Proxy 卸载程序
echo ================================================
echo.

echo 正在停止运行中的程序...
taskkill /IM DeepSeekCursorProxy.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo 正在删除开机自启项...
reg delete "%RUN_KEY%" /v DeepSeekCursorProxy /f >nul 2>&1

echo 正在删除快捷方式...
if exist "%START_MENU%" rmdir /S /Q "%START_MENU%"
powershell -Command "$desktop = [Environment]::GetFolderPath('Desktop'); $lnk = Join-Path $desktop 'DeepSeek Cursor Proxy.lnk'; if (Test-Path $lnk) { Remove-Item $lnk -Force }"

echo 正在删除程序文件...
if exist "%INSTALL_DIR%" (
    rmdir /S /Q "%INSTALL_DIR%"
)

echo.
echo ================================================
echo   卸载完成
echo ================================================
echo.
echo 用户配置目录未删除：%USERPROFILE%\.deepseek-cursor-proxy
echo 如需清除配置，请手动删除上述目录。
echo.
pause
