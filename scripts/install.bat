@echo off
chcp 65001 >nul
title DeepSeek Cursor Proxy 安装

set "INSTALL_DIR=%LOCALAPPDATA%\Programs\DeepSeekCursorProxy"
set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\DeepSeek Cursor Proxy"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"

echo ================================================
echo   DeepSeek Cursor Proxy 安装程序
echo ================================================
echo.
echo 正在安装到: %INSTALL_DIR%
echo.

if exist "%INSTALL_DIR%" (
    echo 检测到已有安装。
    set /p "OVERWRITE=是否覆盖现有安装？(Y/N): "
    if /I not "%OVERWRITE%"=="Y" (
        echo 安装已取消。
        pause
        exit /b 0
    )
    taskkill /IM DeepSeekCursorProxy.exe /F >nul 2>&1
)

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo 正在复制文件...
xcopy /E /Y /I /Q "%~dp0*" "%INSTALL_DIR%\"

if not exist "%START_MENU%" mkdir "%START_MENU%"

powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%START_MENU%\DeepSeek Cursor Proxy.lnk'); $Shortcut.TargetPath = '%INSTALL_DIR%\DeepSeekCursorProxy.exe'; $Shortcut.WorkingDirectory = '%INSTALL_DIR%'; $Shortcut.IconLocation = '%INSTALL_DIR%\app_icon.ico,0'; $Shortcut.Save()"

powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Desktop = [Environment]::GetFolderPath('Desktop'); $Shortcut = $WshShell.CreateShortcut($Desktop + '\DeepSeek Cursor Proxy.lnk'); $Shortcut.TargetPath = '%INSTALL_DIR%\DeepSeekCursorProxy.exe'; $Shortcut.WorkingDirectory = '%INSTALL_DIR%'; $Shortcut.IconLocation = '%INSTALL_DIR%\app_icon.ico,0'; $Shortcut.Save()"

powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%START_MENU%\卸载 DeepSeek Cursor Proxy.lnk'); $Shortcut.TargetPath = '%INSTALL_DIR%\uninstall.bat'; $Shortcut.WorkingDirectory = '%INSTALL_DIR%'; $Shortcut.Save()"

echo.
set /p "AUTOSTART=是否设置登录 Windows 时自动启动？(Y/N): "
if /I "%AUTOSTART%"=="Y" (
    reg add "%RUN_KEY%" /v DeepSeekCursorProxy /t REG_SZ /d "\"%INSTALL_DIR%\DeepSeekCursorProxy.exe\"" /f >nul
    echo 已启用开机自动启动。
) else (
    reg delete "%RUN_KEY%" /v DeepSeekCursorProxy /f >nul 2>&1
)

echo.
echo ================================================
echo   安装完成！
echo ================================================
echo.
echo 快捷方式已创建：
echo   - 开始菜单: DeepSeek Cursor Proxy
echo   - 开始菜单: 卸载 DeepSeek Cursor Proxy
echo   - 桌面: DeepSeek Cursor Proxy
echo.
echo 首次启动时会引导你配置 ngrok authtoken。
echo.
pause
