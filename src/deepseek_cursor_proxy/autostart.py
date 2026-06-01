"""登录后自动启动 GUI（Windows 注册表 Run 项）。"""

from __future__ import annotations

import sys
from pathlib import Path

AUTOSTART_VALUE_NAME = "DeepSeekCursorProxy"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def supports_login_autostart() -> bool:
    return sys.platform == "win32"


def default_installed_executable() -> Path:
    return (
        Path.home()
        / "AppData"
        / "Local"
        / "Programs"
        / "DeepSeekCursorProxy"
        / "DeepSeekCursorProxy.exe"
    )


def resolve_autostart_executable() -> Path | None:
    """返回应写入开机启动项的可执行文件路径。"""
    if not supports_login_autostart():
        return None
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    installed = default_installed_executable()
    if installed.is_file():
        return installed.resolve()
    return None


def is_login_autostart_enabled() -> bool:
    if not supports_login_autostart():
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
            return bool(str(value).strip())
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_login_autostart(enabled: bool) -> tuple[bool, str]:
    """启用或禁用登录后自动启动。返回 (成功, 说明信息)。"""
    if not supports_login_autostart():
        return False, "unsupported_platform"

    import winreg

    if enabled:
        exe_path = resolve_autostart_executable()
        if exe_path is None:
            return False, "executable_not_found"
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                _RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key,
                    AUTOSTART_VALUE_NAME,
                    0,
                    winreg.REG_SZ,
                    str(exe_path),
                )
        except OSError as exc:
            return False, str(exc)
        _remove_legacy_startup_bat()
        return True, str(exe_path)

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
    except FileNotFoundError:
        pass
    except OSError as exc:
        return False, str(exc)
    return True, "disabled"


def _remove_legacy_startup_bat() -> None:
    legacy_bat = (
        Path.home()
        / "AppData"
        / "Roaming"
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "DeepSeekCursorProxy-startup.bat"
    )
    legacy_bat.unlink(missing_ok=True)
