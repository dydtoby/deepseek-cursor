"""Cloudflare Tunnel 提供商 — 使用 cloudflared 创建公网隧道。

支持三种模式：
1. TryCloudflare 快速隧道（免费，无需账号）— **注意：不支持 SSE 流式传输**
2. 命名隧道（需要 Cloudflare 账号和域名，支持 SSE）
3. 自动下载 cloudflared 二进制文件

同时提供 Cloudflare AI Gateway 集成支持。
"""

from __future__ import annotations

import json
import os
import platform as plat
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
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

CLOUDFLARED_BINARY_NAME = "cloudflared"
if plat.system() == "Windows":
    CLOUDFLARED_BINARY_NAME = "cloudflared.exe"

CLOUDFLARED_VERSION = "2025.2.1"
CLOUDFLARED_DOWNLOAD_BASE = "https://github.com/cloudflare/cloudflared/releases/download"

# 各平台下载 URL
CLOUDFLARED_DOWNLOADS: dict[str, str] = {
    "windows_amd64": f"{CLOUDFLARED_DOWNLOAD_BASE}/{CLOUDFLARED_VERSION}/cloudflared-windows-amd64.exe",
    "darwin_amd64": f"{CLOUDFLARED_DOWNLOAD_BASE}/{CLOUDFLARED_VERSION}/cloudflared-darwin-amd64.tgz",
    "darwin_arm64": f"{CLOUDFLARED_DOWNLOAD_BASE}/{CLOUDFLARED_VERSION}/cloudflared-darwin-arm64.tgz",
    "linux_amd64": f"{CLOUDFLARED_DOWNLOAD_BASE}/{CLOUDFLARED_VERSION}/cloudflared-linux-amd64",
    "linux_arm64": f"{CLOUDFLARED_DOWNLOAD_BASE}/{CLOUDFLARED_VERSION}/cloudflared-linux-arm64",
}

# TryCloudflare 快速隧道输出中的 URL 匹配模式
CLOUDFLARE_TRY_URL_PREFIX = "https://"
CLOUDFLARE_TRY_URL_SUFFIX = ".trycloudflare.com"

# AI Gateway 端点格式
AI_GATEWAY_URL_TEMPLATE = "https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/deepseek"


def _get_platform_key() -> str:
    """获取当前平台标识（用于下载正确的 cloudflared 版本）。"""
    system = plat.system().lower()
    machine = plat.machine().lower()

    if system == "windows":
        return "windows_amd64"
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            return "darwin_arm64"
        return "darwin_amd64"
    elif system == "linux":
        if machine in ("arm64", "aarch64"):
            return "linux_arm64"
        return "linux_amd64"
    return "linux_amd64"


def _get_cloudflared_dir() -> Path:
    """cloudflared 安装目录。"""
    return Path.home() / ".cloudflared"


def _get_cloudflared_path() -> Path:
    """cloudflared 二进制文件完整路径。"""
    return _get_cloudflared_dir() / CLOUDFLARED_BINARY_NAME


def _find_cloudflared_on_path() -> str | None:
    """在 PATH 和常见安装位置查找 cloudflared。"""
    which = shutil.which(CLOUDFLARED_BINARY_NAME)
    if which:
        return which

    common_paths = [
        _get_cloudflared_path(),
        Path("/usr/local/bin") / CLOUDFLARED_BINARY_NAME,
        Path("/opt/homebrew/bin") / CLOUDFLARED_BINARY_NAME,
    ]
    for p in common_paths:
        if p.is_file():
            return str(p)
    return None


def download_cloudflared() -> str:
    """下载 cloudflared 二进制文件到 ~/.cloudflared 目录。

    Returns:
        cloudflared 二进制文件的路径。
    """
    platform_key = _get_platform_key()
    download_url = CLOUDFLARED_DOWNLOADS.get(platform_key)
    if not download_url:
        raise RuntimeError(f"不支持的平台: {platform_key}")

    install_dir = _get_cloudflared_dir()
    install_dir.mkdir(parents=True, exist_ok=True)
    target_path = install_dir / CLOUDFLARED_BINARY_NAME

    LOG.info("正在下载 cloudflared v%s (%s)...", CLOUDFLARED_VERSION, platform_key)
    LOG.info("下载地址: %s", download_url)

    try:
        # 下载到临时文件
        tmp_path = target_path.with_suffix(target_path.suffix + ".download")
        urllib.request.urlretrieve(download_url, str(tmp_path))

        if download_url.endswith(".tgz"):
            # macOS: 解压 tar.gz
            import tarfile
            with tarfile.open(str(tmp_path), "r:gz") as tar:
                member = None
                for m in tar.getmembers():
                    if m.name.endswith("cloudflared") and not m.isdir():
                        member = m
                        break
                if member is None:
                    raise RuntimeError("tgz 中未找到 cloudflared")
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise RuntimeError("解压失败")
                target_path.write_bytes(extracted.read())
            tmp_path.unlink()
        else:
            # Windows/Linux: 直接重命名
            tmp_path.rename(target_path)

        # 设置可执行权限
        if plat.system() != "Windows":
            target_path.chmod(0o755)

        LOG.info("cloudflared 下载完成: %s", target_path)
        return str(target_path)

    except Exception as exc:
        LOG.error("下载 cloudflared 失败: %s", exc)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"下载 cloudflared 失败: {exc}\n"
            f"请手动从 https://github.com/cloudflare/cloudflared/releases 下载并放置到 {install_dir}"
        ) from exc


def get_or_download_cloudflared() -> str:
    """获取 cloudflared 二进制文件路径，如不存在则下载。"""
    existing = _find_cloudflared_on_path()
    if existing:
        return existing
    return download_cloudflared()


# ---------------------------------------------------------------------------
# URL 提取
# ---------------------------------------------------------------------------


def _extract_trycloudflare_url(output: str) -> str | None:
    """从 cloudflared 输出中提取 TryCloudflare URL。"""
    for line in output.splitlines():
        stripped = line.strip()
        if CLOUDFLARE_TRY_URL_PREFIX in stripped and CLOUDFLARE_TRY_URL_SUFFIX in stripped:
            for part in stripped.split():
                if part.startswith(CLOUDFLARE_TRY_URL_PREFIX) and CLOUDFLARE_TRY_URL_SUFFIX in part:
                    return part.rstrip(",.;")
    return None


def _extract_named_tunnel_url(output: str) -> str | None:
    """从命名隧道输出中提取 URL。"""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("https://") and "trycloudflare.com" not in stripped:
            for part in stripped.split():
                if part.startswith("https://"):
                    return part.rstrip(",.;")
    return None


# ---------------------------------------------------------------------------
# AI Gateway 辅助
# ---------------------------------------------------------------------------


def build_ai_gateway_url(account_id: str, gateway_id: str) -> str:
    """构建 Cloudflare AI Gateway URL（用于 DeepSeek）。"""
    return AI_GATEWAY_URL_TEMPLATE.format(
        account_id=account_id.strip(),
        gateway_id=gateway_id.strip(),
    )


def is_ai_gateway_configured(config: ProviderConfig) -> bool:
    """检查是否配置了 AI Gateway。"""
    return bool(config.cloudflare_token and "/" in config.cloudflare_token)


# ---------------------------------------------------------------------------
# CloudflareTunnelProvider
# ---------------------------------------------------------------------------


class CloudflareTunnelProvider(BaseTunnelProvider):
    """Cloudflare Tunnel 提供商。

    - TryCloudflare 模式：免费快速隧道（注意：不支持 SSE/流式传输）
    - 命名隧道模式：需要 Cloudflare 账号和域名（支持 SSE）
    - AI Gateway 模式：通过 Cloudflare AI Gateway 代理 DeepSeek API 请求
    """

    def __init__(self, startup_timeout: float = 30.0) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._public_url: str | None = None
        self._startup_timeout = startup_timeout
        self._mode: str = "trycloudflare"  # trycloudflare | named | ai_gateway
        self._tunnel_name: str = ""
        self._ai_gateway_url: str = ""
        self._sse_warning_shown: bool = False

    # ------------------------------------------------------------------
    # BaseTunnelProvider 接口
    # ------------------------------------------------------------------

    @staticmethod
    def provider_type() -> TunnelProviderType:
        return TunnelProviderType.CLOUDFLARE

    @staticmethod
    def provider_name() -> str:
        return "Cloudflare Tunnel"

    @staticmethod
    def provider_description() -> str:
        return (
            "Cloudflare Tunnel — TryCloudflare 免费隧道（不支持流式传输）"
            " 或命名隧道（需 Cloudflare 账号，支持 SSE）"
        )

    def is_available(self) -> bool:
        return _find_cloudflared_on_path() is not None

    def configure(self, config: ProviderConfig) -> None:
        """根据配置选择隧道模式。

        cloudflare_token 格式：
        - 空或 None: TryCloudflare 模式
        - "account_id/gateway_id": AI Gateway 模式
        - "tunnel_name": 命名隧道模式
        """
        token = (config.cloudflare_token or "").strip()

        if not token:
            self._mode = "trycloudflare"
        elif "/" in token:
            # AI Gateway 模式: "account_id/gateway_id"
            parts = token.split("/", 1)
            self._mode = "ai_gateway"
            self._ai_gateway_url = build_ai_gateway_url(parts[0], parts[1])
            self._tunnel_name = ""
        else:
            # 命名隧道模式
            self._mode = "named"
            self._tunnel_name = token

    def start(self, host: str, port: int, *, timeout: float = 30.0) -> TunnelInfo:
        self._startup_timeout = timeout
        local_host = host.strip() or "127.0.0.1"
        if local_host in {"0.0.0.0", "::"}:
            local_host = "127.0.0.1"
        target_url = f"http://{local_host}:{port}"

        # 自动下载 cloudflared
        cloudflared_bin = get_or_download_cloudflared()

        if self._mode == "trycloudflare":
            # TryCloudflare 不支持 SSE
            if not self._sse_warning_shown:
                LOG.warning(
                    "Cloudflare TryCloudflare 快速隧道不支持 Server-Sent Events (SSE)。\n"
                    "如果你使用 DeepSeek 的流式输出 (stream=true)，请求可能会失败。\n"
                    "建议：配置命名隧道或使用 Cloudflare AI Gateway。"
                )
                self._sse_warning_shown = True
            return self._start_trycloudflare(cloudflared_bin, target_url)
        elif self._mode == "named":
            return self._start_named_tunnel(cloudflared_bin, target_url)
        else:
            # AI Gateway 模式：返回网关 URL（不启动本地隧道）
            return TunnelInfo(
                public_url=self._ai_gateway_url,
                provider=TunnelProviderType.CLOUDFLARE,
                reused=False,
            )

    def stop(self) -> None:
        if self._process is None or self._process.poll() is not None:
            return
        LOG.info("stopping cloudflared tunnel")
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=5)
        self._public_url = None

    def is_running(self) -> bool:
        if self._mode == "ai_gateway":
            return self._ai_gateway_url != ""
        return self._process is not None and self._process.poll() is None

    def validate_config(self) -> bool:
        if self._mode == "trycloudflare":
            return self.is_available()
        if self._mode == "ai_gateway":
            return bool(self._ai_gateway_url)
        if self._mode == "named":
            return bool(self._tunnel_name) and self.is_available()
        return False

    def diagnostic(self) -> ProviderDiagnostic:
        diag = ProviderDiagnostic(provider_name=self.provider_name())
        cloudflared_bin = _find_cloudflared_on_path()
        if not cloudflared_bin:
            diag.ok = False
            diag.error = "未找到 cloudflared 二进制文件。将自动尝试下载。"
            diag.extra["auto_download"] = True
            return diag

        try:
            result = subprocess.run(
                [cloudflared_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            diag.version = result.stdout.strip().split("\n")[0] if result.stdout else "unknown"
        except Exception as exc:
            diag.ok = False
            diag.error = str(exc)

        diag.extra["mode"] = self._mode
        return diag

    # ------------------------------------------------------------------
    # TryCloudflare 快速隧道
    # ------------------------------------------------------------------

    def _start_trycloudflare(self, binary: str, target_url: str) -> TunnelInfo:
        LOG.info("starting TryCloudflare tunnel for %s (SSE not supported)", target_url)
        # 清理可能干扰的配置文件
        self._cleanup_config_for_trycloudflare()

        argv = [
            binary,
            "tunnel",
            "--url",
            target_url,
            "--no-autoupdate",
            "--protocol", "http2",  # 使用 HTTP/2 以改善兼容性
        ]

        self._process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        public_url = self._wait_for_public_url("trycloudflare")
        self._public_url = public_url
        return TunnelInfo(
            public_url=public_url,
            provider=TunnelProviderType.CLOUDFLARE,
            reused=False,
        )

    # ------------------------------------------------------------------
    # 命名隧道
    # ------------------------------------------------------------------

    def _start_named_tunnel(self, binary: str, target_url: str) -> TunnelInfo:
        LOG.info("starting named Cloudflare tunnel '%s' for %s", self._tunnel_name, target_url)

        # 检查隧道是否存在
        result = subprocess.run(
            [binary, "tunnel", "list", "--name", self._tunnel_name],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0 or self._tunnel_name not in result.stdout:
            raise RuntimeError(
                f"未找到命名隧道 '{self._tunnel_name}'。\n"
                "请先运行: cloudflared tunnel login\n"
                f"然后: cloudflared tunnel create {self._tunnel_name}"
            )

        argv = [
            binary,
            "tunnel",
            "run",
            "--url", target_url,
            self._tunnel_name,
        ]

        self._process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        public_url = self._wait_for_public_url("named")
        self._public_url = public_url
        return TunnelInfo(
            public_url=public_url,
            provider=TunnelProviderType.CLOUDFLARE,
            reused=False,
        )

    # ------------------------------------------------------------------
    # URL 等待
    # ------------------------------------------------------------------

    def _wait_for_public_url(self, mode: str) -> str:
        """等待 cloudflared 建立隧道并返回公网 URL。"""
        deadline = time.monotonic() + self._startup_timeout
        output_lines: list[str] = []

        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                output = "".join(output_lines)
                if self._process.stdout is not None:
                    output += self._process.stdout.read()
                raise RuntimeError(
                    f"cloudflared exited before creating a tunnel:\n{output.strip()[:500]}"
                )

            if self._process is not None and self._process.stdout is not None:
                line = self._process.stdout.readline()
                if line:
                    output_lines.append(line)

                    # TryCloudflare URL
                    if mode == "trycloudflare":
                        url = _extract_trycloudflare_url(line)
                        if url:
                            LOG.info("TryCloudflare URL: %s", url)
                            return url
                    else:
                        url = _extract_named_tunnel_url(line)
                        if url:
                            LOG.info("Named tunnel URL: %s", url)
                            return url

                    # 检查启动成功标记
                    combined = "".join(output_lines)
                    if "Your free tunnel has started" in combined:
                        url = _extract_trycloudflare_url(combined)
                        if url:
                            LOG.info("TryCloudflare URL: %s", url)
                            return url

                    if "Registered tunnel connection" in line or "Connection registered" in line:
                        # 命名隧道连接成功，但可能没有直接给出 URL
                        # 用户需要知道 DNS 记录中配置的域名
                        pass

            time.sleep(0.2)

        output = "".join(output_lines)
        raise RuntimeError(
            f"Timed out waiting for Cloudflare tunnel URL:\n{output.strip()[:500]}"
        )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _cleanup_config_for_trycloudflare(self) -> None:
        """重命名 .cloudflared/config.yml 以避免干扰 TryCloudflare（已知问题）。"""
        config_dir = _get_cloudflared_dir()
        for name in ("config.yml", "config.yaml"):
            config_file = config_dir / name
            if config_file.is_file():
                backup = config_file.with_suffix(config_file.suffix + ".trycloudflare.bak")
                try:
                    config_file.rename(backup)
                    LOG.info("已重命名 %s -> %s 以启用 TryCloudflare", config_file, backup)
                except OSError:
                    pass
