@echo off
chcp 65001 >nul
title DeepSeek Cursor Proxy 安装

echo ================================================
echo   DeepSeek Cursor Proxy 安装程序
echo ================================================
echo.
echo 正在安装到: %LOCALAPPDATA%\Programs\DeepSeekCursorProxy
echo.

if not exist "%LOCALAPPDATA%\Programs\DeepSeekCursorProxy" (
    mkdir "%LOCALAPPDATA%\Programs\DeepSeekCursorProxy"
)

echo 正在复制文件...
xcopy /E /Y /Q "%~dp0*" "%LOCALAPPDATA%\Programs\DeepSeekCursorProxy\"

set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\DeepSeek Cursor Proxy"
if not exist "%START_MENU%" mkdir "%START_MENU%"

powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%START_MENU%\DeepSeek Cursor Proxy.lnk'); $Shortcut.TargetPath = '%LOCALAPPDATA%\Programs\DeepSeekCursorProxy\DeepSeekCursorProxy.exe'; $Shortcut.WorkingDirectory = '%LOCALAPPDATA%\Programs\DeepSeekCursorProxy'; $Shortcut.IconLocation = '%LOCALAPPDATA%\Programs\DeepSeekCursorProxy\app_icon.ico,0'; $Shortcut.Save()"

powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Desktop = [Environment]::GetFolderPath('Desktop'); $Shortcut = $WshShell.CreateShortcut($Desktop + '\DeepSeek Cursor Proxy.lnk'); $Shortcut.TargetPath = '%LOCALAPPDATA%\Programs\DeepSeekCursorProxy\DeepSeekCursorProxy.exe'; $Shortcut.WorkingDirectory = '%LOCALAPPDATA%\Programs\DeepSeekCursorProxy'; $Shortcut.IconLocation = '%LOCALAPPDATA%\Programs\DeepSeekCursorProxy\app_icon.ico,0'; $Shortcut.Save()"

echo.
echo ================================================
echo   安装完成！
echo ================================================
echo.
echo 快捷方式已创建：
echo   - 开始菜单: DeepSeek Cursor Proxy
echo   - 桌面: DeepSeek Cursor Proxy
echo.
echo 首次启动时会引导你配置 ngrok authtoken。
echo.
pause
