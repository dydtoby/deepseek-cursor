"""ngrok 生命周期管理器 — 查找、配置 authtoken、验证、启动/停止隧道。"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import yaml

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


def ngrok_config_paths() -> list[Path]:
    """所有可能存放 ngrok authtoken 的配置文件路径。"""
    paths = [ngrok_config_path()]
    legacy = Path.home() / ".ngrok2" / NGROK_CONFIG_FILE_NAME
    if legacy not in paths:
        paths.append(legacy)
    return paths


def read_authtoken_from_file(config_file: Path) -> str | None:
    if not config_file.is_file():
        return None
    try:
        content = config_file.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        data = None
    if isinstance(data, dict):
        token = data.get("authtoken")
        if isinstance(token, str) and token.strip():
            return token.strip()

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("authtoken:"):
            value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
        if stripped.startswith("- authtoken:"):
            value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    return None


def read_authtoken() -> str | None:
    """读取当前生效的 ngrok authtoken（仅主配置文件）。"""
    return read_authtoken_from_file(ngrok_config_path())


def write_authtoken_to_config(config_file: Path, token: str) -> None:
    """将 authtoken 直接写入 ngrok 配置文件。"""
    stripped = token.strip()
    if not stripped:
        raise ValueError("ngrok authtoken 不能为空")

    config_file.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if config_file.is_file():
        try:
            loaded = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            loaded = None
        if isinstance(loaded, dict):
            data = loaded

    if "version" not in data:
        data["version"] = "2"
    data["authtoken"] = stripped
    config_file.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def wait_for_authtoken_in_file(
    config_file: Path,
    expected: str,
    *,
    timeout: float = 2.0,
) -> str | None:
    """等待配置文件中出现期望的 authtoken。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        saved = read_authtoken_from_file(config_file)
        if saved == expected:
            return saved
        time.sleep(0.1)
    return read_authtoken_from_file(config_file)


def stop_ngrok_processes() -> None:
    """停止可能占用 4040 端口或缓存旧会话的 ngrok 进程。"""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/IM", "ngrok.exe", "/F"],
            capture_output=True,
            text=True,
        )
        return

    subprocess.run(
        ["pkill", "-f", "ngrok"],
        capture_output=True,
        text=True,
    )


def configure_authtoken(
    token: str,
    ngrok_binary: str | None = None,
    *,
    verify: bool = True,
) -> bool:
    """运行 `ngrok config add-authtoken <token>` 并验证写入结果。"""
    stripped = token.strip()
    if not stripped:
        raise ValueError("ngrok authtoken 不能为空")

    ngrok_bin = ngrok_binary or find_ngrok_binary()
    config_file = ngrok_config_path()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    stop_ngrok_processes()

    legacy_config = Path.home() / ".ngrok2" / NGROK_CONFIG_FILE_NAME
    if legacy_config.is_file() and legacy_config != config_file:
        clear_authtoken_from_file(legacy_config)

    config_path_arg = config_file.resolve().as_posix()
    result = subprocess.run(
        [
            ngrok_bin,
            "config",
            "add-authtoken",
            stripped,
            f"--config={config_path_arg}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        write_authtoken_to_config(config_file, stripped)
        if read_authtoken_from_file(config_file) != stripped:
            raise RuntimeError(
                f"ngrok authtoken 配置失败（退出码 {result.returncode}）:\n{stderr}"
            )
    else:
        saved = wait_for_authtoken_in_file(config_file, stripped)
        if saved != stripped:
            write_authtoken_to_config(config_file, stripped)

    saved = read_authtoken_from_file(config_file)
    if saved != stripped:
        raise RuntimeError(
            "ngrok authtoken 未成功写入配置文件: "
            f"{config_file}"
        )

    if verify:
        verify_authtoken_connectivity(ngrok_binary=ngrok_bin)

    return True


def verify_authtoken_connectivity(
    ngrok_binary: str | None = None,
    timeout: float = 8.0,
) -> None:
    """验证 authtoken 能建立 ngrok 隧道会话。"""
    ngrok_bin = ngrok_binary or find_ngrok_binary()
    config_file = ngrok_config_path()
    probe_port = random.randint(20000, 40000)
    target = f"127.0.0.1:{probe_port}"

    proc = subprocess.Popen(
        [
            ngrok_bin,
            "http",
            target,
            f"--config={config_file}",
            "--log=stdout",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    collected: list[str] = []
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.stdout is not None:
                line = proc.stdout.readline()
                if line:
                    collected.append(line)
                    lowered = line.lower()
                    if "started tunnel" in lowered or "tunnel session started" in lowered:
                        return
                    if "authentication failed" in lowered or "err_ngrok_" in lowered:
                        raise RuntimeError("".join(collected).strip())

            if proc.poll() is not None:
                output = "".join(collected)
                if proc.stdout is not None:
                    output += proc.stdout.read()
                if "started tunnel" in output.lower():
                    return
                if output.strip():
                    raise RuntimeError(output.strip())
                raise RuntimeError("ngrok exited before authtoken verification completed")

            time.sleep(0.1)

        raise RuntimeError("Timed out verifying ngrok authtoken")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)


def validate_authtoken() -> bool:
    """检查 ngrok authtoken 是否已配置且非空。"""
    return read_authtoken() is not None


def is_missing_authtoken_error(message: str) -> bool:
    """判断 ngrok 报错是否由缺失/无效 authtoken 引起。"""
    normalized = message.lower()
    return (
        "err_ngrok_4018" in normalized
        or "requires a verified account and authtoken" in normalized
    )


def has_authtoken_configured() -> bool:
    """检查 ngrok authtoken 是否已配置。"""
    return validate_authtoken()


def clear_authtoken_from_file(config_file: Path) -> bool:
    """从单个 ngrok 配置文件中移除 authtoken。"""
    if not config_file.is_file():
        return False

    try:
        content = config_file.read_text(encoding="utf-8")
    except OSError:
        return False

    removed = False
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        data = None

    if isinstance(data, dict) and "authtoken" in data:
        del data["authtoken"]
        config_file.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return True

    kept_lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("authtoken:") or stripped.startswith("authtoken "):
            removed = True
            continue
        kept_lines.append(line)

    if not removed:
        return False

    text = "\n".join(kept_lines)
    if text and not text.endswith("\n"):
        text += "\n"
    config_file.write_text(text, encoding="utf-8")
    return True


def clear_authtoken() -> bool:
    """从所有 ngrok 配置文件中移除 authtoken。"""
    stop_ngrok_processes()
    cleared_any = False
    for config_file in ngrok_config_paths():
        if clear_authtoken_from_file(config_file):
            cleared_any = True
    return cleared_any


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
            config_path=str(ngrok_config_path()),
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
