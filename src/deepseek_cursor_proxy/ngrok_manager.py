"""ngrok 生命周期管理器 — 查找、配置 authtoken、验证、启动/停止隧道。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .tunnel import (
    DEFAULT_NGROK_API_URL,
    NgrokTunnel,
    local_tunnel_target,
    ngrok_agent_urls,
    parse_ngrok_public_url,
)

NGROK_CONFIG_FILE_NAME = "ngrok.yml"


# ---------------------------------------------------------------------------
# 查找 ngrok 可执行文件
# ---------------------------------------------------------------------------


def _find_bundled_ngrok() -> str | None:
    """在 PyInstaller 打包环境中查找 ngrok.exe。

    查找顺序：
    1. sys._MEIPASS（PyInstaller 临时解压目录）
    2. 可执行文件所在目录
    3. 项目源代码目录下的 assets/
    """
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "ngrok.exe")

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "ngrok.exe")

    # 开发模式：项目根目录下的 assets/
    repo_root = Path(__file__).resolve().parents[3]
    candidates.append(repo_root / "assets" / "ngrok.exe")

    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def find_ngrok_binary() -> str:
    """找到 ngrok 可执行文件的路径。

    优先使用捆绑的 ngrok，然后回退到系统 PATH。
    """
    bundled = _find_bundled_ngrok()
    if bundled is not None:
        return bundled

    which = shutil.which("ngrok")
    if which is not None:
        return which

    raise FileNotFoundError(
        "未找到 ngrok。请确保 ngrok.exe 已安装或在 PATH 中。\n"
        "下载地址: https://ngrok.com/download"
    )


# ---------------------------------------------------------------------------
# authtoken 管理
# ---------------------------------------------------------------------------


def ngrok_config_dir() -> Path:
    r"""ngrok 配置目录（Windows: %LOCALAPPDATA%\ngrok）。"""
    if sys.platform == "win32":
        base = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
    else:
        base = Path.home() / ".config"
    return base / "ngrok"


def ngrok_config_path() -> Path:
    """ngrok 配置文件完整路径。"""
    return ngrok_config_dir() / NGROK_CONFIG_FILE_NAME


def configure_authtoken(token: str, ngrok_binary: str | None = None) -> bool:
    """运行 `ngrok config add-authtoken <token>`。

    返回 True 表示配置成功。
    """
    ngrok_bin = ngrok_binary or find_ngrok_binary()
    result = subprocess.run(
        [ngrok_bin, "config", "add-authtoken", token.strip()],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"ngrok authtoken 配置失败（退出码 {result.returncode}）:\n{stderr}"
        )
    return True


def validate_authtoken() -> bool:
    """检查 ngrok authtoken 是否已配置。

    通过检查 ngrok 配置文件是否存在且包含 authtoken 字段。
    """
    config_file = ngrok_config_path()
    if not config_file.is_file():
        return False
    try:
        content = config_file.read_text(encoding="utf-8")
        return "authtoken:" in content
    except OSError:
        return False


def has_authtoken_configured() -> bool:
    """检查 ngrok authtoken 是否已配置。"""
    return validate_authtoken()


# ---------------------------------------------------------------------------
# 隧道生命周期（GUI 友好封装）
# ---------------------------------------------------------------------------


class NgrokTunnelManager:
    """ngrok 隧道管理器 — 供 GUI 直接调用。"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9000,
        ngrok_url: str | None = None,
        startup_timeout: float = 15.0,
    ) -> None:
        self._host = host
        self._port = port
        self._ngrok_url = ngrok_url
        self._startup_timeout = startup_timeout
        self._tunnel: NgrokTunnel | None = None
        self._public_url: str | None = None

    @property
    def public_url(self) -> str | None:
        return self._public_url

    @property
    def is_running(self) -> bool:
        return self._tunnel is not None and (
            self._tunnel.reused_external or self._tunnel.process is not None
        )

    def start(self) -> str:
        """启动 ngrok 隧道，返回公网 HTTPS URL。"""
        ngrok_bin = find_ngrok_binary()
        target = local_tunnel_target(self._host, self._port)

        self._tunnel = NgrokTunnel(
            target_url=target,
            ngrok_url=self._ngrok_url,
            command=ngrok_bin,
            startup_timeout=self._startup_timeout,
        )
        self._public_url = self._tunnel.start()
        return self._public_url

    def stop(self) -> None:
        """停止 ngrok 隧道。"""
        if self._tunnel is not None:
            self._tunnel.stop()
            self._tunnel = None
        self._public_url = None

    def ensure_authtoken(self, token: str) -> None:
        """确保 authtoken 已配置（已配置则跳过）。"""
        if validate_authtoken():
            return
        configure_authtoken(token)


# ---------------------------------------------------------------------------
# 验证 ngrok 是否能正常运行（诊断用）
# ---------------------------------------------------------------------------


def check_ngrok_version(ngrok_binary: str | None = None) -> str:
    """获取 ngrok 版本号字符串。"""
    ngrok_bin = ngrok_binary or find_ngrok_binary()
    result = subprocess.run(
        [ngrok_bin, "version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"无法获取 ngrok 版本: {result.stderr.strip()}")
    return result.stdout.strip().split("\n")[0]


def test_ngrok_connection(ngrok_binary: str | None = None) -> dict[str, Any]:
    """快速诊断 ngrok 是否能工作。

    返回诊断信息 dict：
    - ok: bool
    - version: str
    - authtoken_configured: bool
    - error: str | None
    """
    result: dict[str, Any] = {
        "ok": True,
        "version": "",
        "authtoken_configured": False,
        "error": None,
    }
    try:
        result["version"] = check_ngrok_version(ngrok_binary)
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
        return result

    try:
        result["authtoken_configured"] = validate_authtoken()
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)

    return result
