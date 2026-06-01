"""frp 隧道提供商 — 使用 frpc 客户端连接到 frps 服务器。

frp (Fast Reverse Proxy) 是国内最流行的内网穿透工具。
用户需要提供一台有公网 IP 的服务器（运行 frps），
或使用公共 frp 服务。
"""

from __future__ import annotations

import json
import os
import platform as plat
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from ..tunnel_provider import (
    BaseTunnelProvider,
    ProviderConfig,
    ProviderDiagnostic,
    TunnelInfo,
    TunnelProviderType,
)
from ..logging import LOG

FRPC_BINARY_NAME = "frpc"
if plat.system() == "Windows":
    FRPC_BINARY_NAME = "frpc.exe"


# 一些可供参考的国内公共 frp 服务（用户需要自行确认可用性）
PUBLIC_FRP_SERVERS: list[dict[str, Any]] = [
    {
        "name": "自定义服务器",
        "server_addr": "",
        "server_port": 7000,
        "token": "",
        "description": "使用你自己的 frps 服务器",
    },
]


def _find_frpc_on_path() -> str | None:
    which = shutil.which(FRPC_BINARY_NAME)
    if which:
        return which

    # 常见安装位置
    common_paths = [
        Path.home() / "frp" / FRPC_BINARY_NAME,
        Path("/usr/local/bin") / FRPC_BINARY_NAME,
        Path("/opt/frp") / FRPC_BINARY_NAME,
    ]
    for p in common_paths:
        if p.is_file():
            return str(p)
    return None


def _generate_frpc_config(
    server_addr: str,
    server_port: int,
    local_host: str,
    local_port: int,
    remote_port: int = 0,
    auth_token: str = "",
    protocol: str = "https",
) -> str:
    """生成 frpc.ini 配置文件内容。"""
    lines = [
        "[common]",
        f"server_addr = {server_addr}",
        f"server_port = {server_port}",
    ]
    if auth_token:
        lines.append(f"token = {auth_token}")

    lines.append("")
    lines.append("[deepseek-proxy]")
    lines.append(f"type = {protocol}")
    lines.append(f"local_ip = {local_host}")
    lines.append(f"local_port = {local_port}")

    if remote_port > 0:
        lines.append(f"remote_port = {remote_port}")

    # 对 https 协议启用加密
    if protocol == "https":
        lines.append("use_encryption = true")
        lines.append("use_compression = true")

    return "\n".join(lines) + "\n"


def _extract_frp_public_url(output: str, protocol: str = "https") -> str | None:
    """从 frpc 输出中提取公网 URL。"""
    for line in output.splitlines():
        stripped = line.strip()
        if "success" in stripped.lower() and "proxy" in stripped.lower():
            # 尝试解析 JSON 格式的状态输出
            if stripped.startswith("{"):
                try:
                    data = json.loads(stripped)
                    if isinstance(data, dict):
                        for key in ("url", "public_url", "remote_addr"):
                            val = data.get(key)
                            if isinstance(val, str):
                                if val.startswith("http"):
                                    return val
                                return f"{protocol}://{val}"
                except json.JSONDecodeError:
                    pass

            # 尝试从文本中提取 URL
            words = stripped.split()
            for word in words:
                if word.startswith("http://") or word.startswith("https://"):
                    return word.rstrip(",.;")

    return None


class FrpProvider(BaseTunnelProvider):
    """frp 隧道提供商。

    使用 frpc 客户端连接 frps 服务器。

    配置要求：
    - server_addr: frps 服务器地址（必填）
    - server_port: frps 端口（默认 7000）
    - auth_token: 认证 token
    - remote_port: 远程端口（0 = 自动分配）
    """

    def __init__(self, startup_timeout: float = 30.0) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._public_url: str | None = None
        self._startup_timeout = startup_timeout
        self._config: ProviderConfig = ProviderConfig()
        self._config_file: Path | None = None

    # ------------------------------------------------------------------
    # BaseTunnelProvider 接口
    # ------------------------------------------------------------------

    @staticmethod
    def provider_type() -> TunnelProviderType:
        return TunnelProviderType.FRP

    @staticmethod
    def provider_name() -> str:
        return "frp (Fast Reverse Proxy)"

    @staticmethod
    def provider_description() -> str:
        return "frp — 国内最流行的内网穿透工具，需要一台有公网 IP 的服务器（运行 frps）"

    def is_available(self) -> bool:
        return _find_frpc_on_path() is not None

    def configure(self, config: ProviderConfig) -> None:
        if not config.frp_server_addr:
            raise ValueError("frp 服务器地址不能为空")
        self._config = config

    def start(self, host: str, port: int, *, timeout: float = 30.0) -> TunnelInfo:
        self._startup_timeout = timeout
        local_host = host.strip() or "127.0.0.1"
        if local_host in {"0.0.0.0", "::"}:
            local_host = "127.0.0.1"

        if not self._config.frp_server_addr:
            raise RuntimeError(
                "frp 未配置。请在设置中填写 frp 服务器地址。"
            )

        frpc_bin = _find_frpc_on_path()
        if not frpc_bin:
            raise RuntimeError(
                "未找到 frpc。请从 https://github.com/fatedier/frp/releases 下载，"
                "将 frpc 放入 PATH 或项目目录。"
            )

        # 生成临时配置文件
        config_content = _generate_frpc_config(
            server_addr=self._config.frp_server_addr,
            server_port=self._config.frp_server_port or 7000,
            local_host=local_host,
            local_port=port,
            remote_port=self._config.frp_remote_port or 0,
            auth_token=self._config.frp_auth_token or "",
            protocol=self._config.frp_protocol or "https",
        )

        fd, config_path = tempfile.mkstemp(suffix=".ini", prefix="frpc-deepseek-")
        os.close(fd)
        self._config_file = Path(config_path)
        self._config_file.write_text(config_content, encoding="utf-8")

        try:
            return self._run_frpc(frpc_bin, self._config.frp_protocol or "https")
        except Exception:
            self._cleanup_config()
            raise

    def stop(self) -> None:
        if self._process is None or self._process.poll() is not None:
            return
        LOG.info("stopping frpc tunnel")
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=5)
        self._public_url = None
        self._cleanup_config()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def validate_config(self) -> bool:
        return bool(self.is_available() and self._config.frp_server_addr)

    def diagnostic(self) -> ProviderDiagnostic:
        diag = ProviderDiagnostic(provider_name=self.provider_name())
        frpc_bin = _find_frpc_on_path()
        if not frpc_bin:
            diag.ok = False
            diag.error = "未找到 frpc 二进制文件"
            return diag

        try:
            result = subprocess.run(
                [frpc_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            diag.version = result.stdout.strip().split("\n")[0] if result.stdout else "unknown"
        except Exception as exc:
            diag.ok = False
            diag.error = str(exc)

        diag.extra["server_configured"] = bool(self._config.frp_server_addr)
        return diag

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _run_frpc(self, binary: str, protocol: str) -> TunnelInfo:
        LOG.info(
            "starting frpc tunnel to %s:%s",
            self._config.frp_server_addr,
            self._config.frp_server_port,
        )

        argv = [binary, "-c", str(self._config_file)]

        self._process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        public_url = self._wait_for_frp_url(protocol)
        self._public_url = public_url
        return TunnelInfo(
            public_url=public_url,
            provider=TunnelProviderType.FRP,
            reused=False,
        )

    def _wait_for_frp_url(self, protocol: str) -> str:
        """等待 frpc 建立连接并获取公网 URL。"""
        deadline = time.monotonic() + self._startup_timeout
        output_lines: list[str] = []

        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                output = "".join(output_lines)
                if self._process.stdout is not None:
                    output += self._process.stdout.read()
                raise RuntimeError(
                    f"frpc exited before connecting:\n{output.strip()}"
                )

            if self._process is not None and self._process.stdout is not None:
                line = self._process.stdout.readline()
                if line:
                    output_lines.append(line)
                    url = _extract_frp_public_url(line, protocol)
                    if url:
                        LOG.info("frp public URL: %s", url)
                        return url

                    # 也检查是否有 "start proxy success" 输出
                    if "start proxy success" in line.lower() or "proxy [deepseek-proxy] success" in line.lower():
                        # 构建 URL
                        remote_port = self._config.frp_remote_port
                        if remote_port:
                            url = (
                                f"https://{self._config.frp_server_addr}:{remote_port}"
                                if protocol == "https"
                                else f"http://{self._config.frp_server_addr}:{remote_port}"
                            )
                            LOG.info("frp public URL (constructed): %s", url)
                            return url

            time.sleep(0.3)

        output = "".join(output_lines)
        raise RuntimeError(
            f"Timed out waiting for frp connection:\n{output.strip()}"
        )

    def _cleanup_config(self) -> None:
        if self._config_file is not None:
            self._config_file.unlink(missing_ok=True)
            self._config_file = None
