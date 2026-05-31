"""ngrok 生命周期管理器 — 查找、配置 authtoken、验证、启动/停止隧道。"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import yaml

from .platform_support import (
    find_bundled_ngrok,
    find_ngrok_on_path,
    legacy_ngrok_config_paths as platform_legacy_ngrok_config_paths,
    ngrok_binary_name,
    ngrok_config_dir,
    stop_ngrok_processes,
)
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
    """在 PyInstaller 打包环境或项目 assets 中查找 ngrok 可执行文件。"""
    repo_root = Path(__file__).resolve().parents[3]
    return find_bundled_ngrok(
        repo_root,
        frozen=bool(getattr(sys, "frozen", False)),
    )


def find_ngrok_binary() -> str:
    """找到 ngrok 可执行文件的路径。

    优先使用捆绑的 ngrok，然后回退到系统 PATH。
    """
    bundled = _find_bundled_ngrok()
    if bundled is not None:
        return bundled

    which = find_ngrok_on_path()
    if which is not None:
        return which

    binary = ngrok_binary_name()
    raise FileNotFoundError(
        f"未找到 ngrok（{binary}）。请确保 ngrok 已安装或在 PATH 中。\n"
        "下载地址: https://ngrok.com/download"
    )


# ---------------------------------------------------------------------------
# authtoken 管理
# ---------------------------------------------------------------------------


def ngrok_config_path() -> Path:
    """ngrok 配置文件完整路径。"""
    return ngrok_config_dir() / NGROK_CONFIG_FILE_NAME


def legacy_ngrok_config_paths() -> list[Path]:
    """旧版 ngrok 可能存放 authtoken 的配置路径（不含主配置）。"""
    return platform_legacy_ngrok_config_paths(ngrok_config_path())


def ngrok_config_paths() -> list[Path]:
    """所有可能存放 ngrok authtoken 的配置文件路径。"""
    return [ngrok_config_path(), *legacy_ngrok_config_paths()]


@dataclass(frozen=True)
class LegacyTokenCleanupResult:
    migrated_from: Path | None = None
    cleared_paths: tuple[Path, ...] = field(default_factory=tuple)
    migrated_token: bool = False

    @property
    def changed(self) -> bool:
        return self.migrated_token or bool(self.cleared_paths)


def migrate_and_cleanup_legacy_tokens() -> LegacyTokenCleanupResult:
    """将旧版路径中的 token 迁移到主配置，并清除所有旧版 token。"""
    primary = ngrok_config_path()
    repair_v3_config_file(primary)
    primary_token = read_authtoken_from_file(primary)
    migrated_from: Path | None = None
    cleared_paths: list[Path] = []

    for legacy_path in legacy_ngrok_config_paths():
        legacy_token = read_authtoken_from_file(legacy_path)
        if legacy_token and not primary_token:
            result = _run_ngrok_add_authtoken(legacy_token, primary)
            if result.returncode == 0:
                primary_token = legacy_token
                migrated_from = legacy_path

        if clear_authtoken_from_file(legacy_path):
            cleared_paths.append(legacy_path)

    return LegacyTokenCleanupResult(
        migrated_from=migrated_from,
        cleared_paths=tuple(cleared_paths),
        migrated_token=migrated_from is not None,
    )


def _token_from_mapping(data: dict[str, Any]) -> str | None:
    token = data.get("authtoken")
    if isinstance(token, str) and token.strip():
        return token.strip()

    agent = data.get("agent")
    if isinstance(agent, dict):
        agent_token = agent.get("authtoken")
        if isinstance(agent_token, str) and agent_token.strip():
            return agent_token.strip()
    return None


def repair_v3_config_file(config_file: Path) -> bool:
    """修复 ngrok v3 配置中被误写入的顶层 authtoken 字段。"""
    if not config_file.is_file():
        return False

    try:
        content = config_file.read_text(encoding="utf-8")
    except OSError:
        return False

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return False

    if not isinstance(data, dict):
        return False

    version = str(data.get("version", "")).strip().strip('"').strip("'")
    if version != "3" or "authtoken" not in data:
        return False

    del data["authtoken"]
    config_file.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return True


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
        token = _token_from_mapping(data)
        if token:
            return token

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("authtoken:"):
            value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    return None


def read_authtoken() -> str | None:
    """读取当前生效的 ngrok authtoken（仅主配置文件）。"""
    return read_authtoken_from_file(ngrok_config_path())


def write_authtoken_to_config(
    config_file: Path,
    token: str,
    ngrok_binary: str | None = None,
) -> None:
    """通过 ngrok CLI 写入 authtoken（兼容 v3 配置格式）。"""
    stripped = token.strip()
    if not stripped:
        raise ValueError("ngrok authtoken 不能为空")

    repair_v3_config_file(config_file)
    result = _run_ngrok_add_authtoken(stripped, config_file, ngrok_binary)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"ngrok authtoken 配置失败（退出码 {result.returncode}）:\n{stderr}"
        )


def _config_path_arg(config_file: Path) -> str:
    return config_file.resolve().as_posix()


def _run_ngrok_add_authtoken(
    token: str,
    config_file: Path,
    ngrok_binary: str | None = None,
) -> subprocess.CompletedProcess[str]:
    ngrok_bin = ngrok_binary or find_ngrok_binary()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            ngrok_bin,
            "config",
            "add-authtoken",
            token.strip(),
            f"--config={_config_path_arg(config_file)}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_ngrok_config_check(
    config_file: Path,
    ngrok_binary: str | None = None,
) -> None:
    ngrok_bin = ngrok_binary or find_ngrok_binary()
    result = subprocess.run(
        [
            ngrok_bin,
            "config",
            "check",
            f"--config={_config_path_arg(config_file)}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ngrok config check failed").strip()
        raise RuntimeError(message)


def _clear_legacy_authtokens() -> tuple[Path, ...]:
    cleared_paths: list[Path] = []
    for legacy_path in legacy_ngrok_config_paths():
        if clear_authtoken_from_file(legacy_path):
            cleared_paths.append(legacy_path)
    return tuple(cleared_paths)


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
    stop_ngrok_processes()
    repair_v3_config_file(config_file)

    result = _run_ngrok_add_authtoken(stripped, config_file, ngrok_bin)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"ngrok authtoken 配置失败（退出码 {result.returncode}）:\n{stderr}"
        )

    saved = wait_for_authtoken_in_file(config_file, stripped)
    if saved != stripped:
        _run_ngrok_config_check(config_file, ngrok_bin)
        saved = read_authtoken_from_file(config_file)
        if saved != stripped:
            raise RuntimeError(
                "ngrok authtoken 未成功写入配置文件: "
                f"{config_file}"
            )

    if verify:
        verify_authtoken_connectivity(ngrok_binary=ngrok_bin)

    _clear_legacy_authtokens()
    return True


def is_endpoint_already_online_error(message: str) -> bool:
    """判断 ngrok 报错是否因固定域名/端点已被占用（ERR_NGROK_334）。"""
    normalized = message.lower()
    return "err_ngrok_334" in normalized or "is already online" in normalized


def _ngrok_session_started(output: str) -> bool:
    lowered = output.lower()
    return (
        "started tunnel" in lowered
        or "tunnel session started" in lowered
        or "starting web service" in lowered
    )


def _create_minimal_probe_config(authtoken: str) -> Path:
    """创建仅含 authtoken 的临时配置，避免用户 ngrok.yml 中的固定域名干扰探测。"""
    fd, path_str = tempfile.mkstemp(suffix=".yml", prefix="ngrok-probe-")
    os.close(fd)
    probe_file = Path(path_str)
    probe_file.write_text(
        yaml.safe_dump(
            {"version": "3", "agent": {"authtoken": authtoken.strip()}},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return probe_file


def _raise_from_ngrok_probe_output(output: str) -> None:
    if is_endpoint_already_online_error(output) and _ngrok_session_started(output):
        return
    if is_missing_authtoken_error(output):
        raise RuntimeError(output.strip())
    if "err_ngrok_334" in output.lower():
        raise RuntimeError(output.strip())
    if "authentication failed" in output.lower() or "err_ngrok_" in output.lower():
        raise RuntimeError(output.strip())
    raise RuntimeError(output.strip() or "ngrok exited before authtoken verification completed")


def verify_authtoken_connectivity(
    ngrok_binary: str | None = None,
    timeout: float = 8.0,
) -> None:
    """验证 authtoken 能建立 ngrok 隧道会话。"""
    ngrok_bin = ngrok_binary or find_ngrok_binary()
    config_file = ngrok_config_path()
    authtoken = read_authtoken_from_file(config_file)
    if not authtoken:
        raise RuntimeError("ngrok authtoken 未写入配置文件，无法验证连通性")

    stop_ngrok_processes()
    probe_config = _create_minimal_probe_config(authtoken)
    probe_port = random.randint(20000, 40000)
    target = f"127.0.0.1:{probe_port}"

    proc = subprocess.Popen(
        [
            ngrok_bin,
            "http",
            target,
            f"--config={_config_path_arg(probe_config)}",
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
                    output = "".join(collected)
                    if _ngrok_session_started(output):
                        return
                    lowered = line.lower()
                    if "authentication failed" in lowered:
                        raise RuntimeError(output.strip())
                    if "err_ngrok_" in lowered:
                        if is_endpoint_already_online_error(output):
                            if _ngrok_session_started(output):
                                return
                        _raise_from_ngrok_probe_output(output)

            if proc.poll() is not None:
                output = "".join(collected)
                if proc.stdout is not None:
                    output += proc.stdout.read()
                if _ngrok_session_started(output):
                    return
                if output.strip():
                    _raise_from_ngrok_probe_output(output)
                raise RuntimeError("ngrok exited before authtoken verification completed")

            time.sleep(0.1)

        raise RuntimeError("Timed out verifying ngrok authtoken")
    finally:
        probe_config.unlink(missing_ok=True)
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
        or "field authtoken not found" in normalized
        or "error reading configuration file" in normalized
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
        removed = True

    agent = data.get("agent") if isinstance(data, dict) else None
    if isinstance(agent, dict) and "authtoken" in agent:
        del agent["authtoken"]
        removed = True

    if isinstance(data, dict) and removed:
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
