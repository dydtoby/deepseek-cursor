"""Ngrok 隧道提供商 — 封装 ngrok 隧道的启动、停止和配置管理。"""

from __future__ import annotations

import json
import os
import random
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import URLError
from urllib.request import urlopen

import yaml

from ..tunnel_provider import (
    BaseTunnelProvider,
    ProviderConfig,
    ProviderDiagnostic,
    TunnelInfo,
    TunnelProviderType,
)
from ..platform_support import (
    find_bundled_ngrok,
    find_ngrok_on_path,
    ngrok_binary_name,
    ngrok_config_dir,
    stop_ngrok_processes,
)
from ..logging import LOG

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

NGROK_CONFIG_FILE_NAME = "ngrok.yml"
DEFAULT_NGROK_API_URL = "http://127.0.0.1:4040/api"


# ---------------------------------------------------------------------------
# 辅助函数（从 tunnel.py 移植）
# ---------------------------------------------------------------------------


def _local_tunnel_target(host: str, port: int) -> str:
    local_host = host.strip() or "127.0.0.1"
    if local_host in {"0.0.0.0", "::"}:
        local_host = "127.0.0.1"
    if ":" in local_host and not local_host.startswith("["):
        local_host = f"[{local_host}]"
    return f"http://{local_host}:{port}"


def _parse_ngrok_public_url(payload: dict[str, Any]) -> str | None:
    records = payload.get("endpoints")
    if not isinstance(records, list):
        records = payload.get("tunnels")
    if not isinstance(records, list):
        return None

    public_urls = [
        public_url
        for record in records
        if isinstance(record, dict)
        for public_url in (record.get("url"), record.get("public_url"))
        if isinstance(public_url, str)
    ]
    for public_url in public_urls:
        if public_url.startswith("https://"):
            return public_url
    for public_url in public_urls:
        if public_url.startswith("http://"):
            return public_url
    return None


def _ngrok_agent_urls(api_url: str) -> list[str]:
    normalized = api_url.rstrip("/")
    if normalized.endswith("/endpoints") or normalized.endswith("/tunnels"):
        return [normalized]
    return [f"{normalized}/endpoints", f"{normalized}/tunnels"]


def _normalize_tunnel_addr(addr: str) -> str:
    normalized = addr.strip()
    if normalized.startswith("http://"):
        normalized = normalized[len("http://"):]
    elif normalized.startswith("https://"):
        normalized = normalized[len("https://"):]

    if normalized.startswith("[") and "]" in normalized:
        host, _, remainder = normalized[1:].partition("]")
        port = remainder.lstrip(":")
    else:
        host, _, port = normalized.rpartition(":")

    host = host.strip().lower()
    if host in {"0.0.0.0", "::", "localhost"}:
        host = "127.0.0.1"

    if not port:
        raise ValueError(f"invalid tunnel address: {addr!r}")
    return f"{host}:{port}"


def _tunnel_record_addr(record: dict[str, Any]) -> str | None:
    config = record.get("config")
    if isinstance(config, dict):
        addr = config.get("addr")
        if isinstance(addr, str):
            return addr
    upstream = record.get("upstream")
    if isinstance(upstream, dict):
        upstream_url = upstream.get("url")
        if isinstance(upstream_url, str):
            return upstream_url
    for key in ("addr", "upstream", "upstream_url"):
        value = record.get(key)
        if isinstance(value, str):
            return value
    return None


def _tunnel_record_public_url(record: dict[str, Any]) -> str | None:
    for key in ("url", "public_url"):
        value = record.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def _ngrok_tunnel_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("endpoints")
    if not isinstance(records, list):
        records = payload.get("tunnels")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _fetch_ngrok_agent_payload(api_url: str = DEFAULT_NGROK_API_URL) -> dict[str, Any] | None:
    for endpoint in _ngrok_agent_urls(api_url):
        try:
            with urlopen(endpoint, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _find_existing_public_url(target_url: str, api_url: str = DEFAULT_NGROK_API_URL) -> str | None:
    try:
        expected_addr = _normalize_tunnel_addr(target_url)
    except ValueError:
        return None

    payload = _fetch_ngrok_agent_payload(api_url)
    if payload is None:
        return None

    https_url: str | None = None
    http_url: str | None = None
    for record in _ngrok_tunnel_records(payload):
        addr = _tunnel_record_addr(record)
        if addr is None:
            continue
        try:
            if _normalize_tunnel_addr(addr) != expected_addr:
                continue
        except ValueError:
            continue

        public_url = _tunnel_record_public_url(record)
        if public_url is None:
            continue
        if public_url.startswith("https://"):
            return public_url
        if http_url is None:
            http_url = public_url

    return https_url or http_url


def _read_ngrok_stderr(stderr_handle: BinaryIO | None) -> str:
    if stderr_handle is None:
        return ""
    try:
        stderr_handle.seek(0)
        text = stderr_handle.read().decode("utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return ""
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _is_endpoint_already_online_error(message: str) -> bool:
    normalized = message.lower()
    return "err_ngrok_334" in normalized or "is already online" in normalized


# ---------------------------------------------------------------------------
# NgrokProvider
# ---------------------------------------------------------------------------


class NgrokProvider(BaseTunnelProvider):
    """ngrok 隧道提供商。

    使用本地 ngrok 二进制文件创建公网 HTTPS 隧道。
    """

    def __init__(
        self,
        api_url: str = DEFAULT_NGROK_API_URL,
        startup_timeout: float = 30.0,
    ) -> None:
        self._host: str = "127.0.0.1"
        self._port: int = 9000
        self._ngrok_url: str | None = None
        self._startup_timeout = startup_timeout
        self._api_url = api_url
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr_handle: tempfile.SpooledTemporaryFile[bytes] | None = None
        self._reused: bool = False
        self._public_url: str | None = None

    # ------------------------------------------------------------------
    # BaseTunnelProvider 接口
    # ------------------------------------------------------------------

    @staticmethod
    def provider_type() -> TunnelProviderType:
        return TunnelProviderType.NGROK

    @staticmethod
    def provider_name() -> str:
        return "ngrok"

    @staticmethod
    def provider_description() -> str:
        return "ngrok — 创建公网 HTTPS 隧道（需要 ngrok 账号，中国境内可能受限）"

    def is_available(self) -> bool:
        try:
            self._find_ngrok_binary()
            return True
        except FileNotFoundError:
            return False

    def configure(self, config: ProviderConfig) -> None:
        ngrok_bin = self._find_ngrok_binary()
        token = config.ngrok_auth_token

        if token and token.strip():
            self._configure_authtoken(token.strip(), ngrok_bin)
            # 验证连通性
            self._verify_authtoken_connectivity(ngrok_bin)

        self._ngrok_url = config.ngrok_url

        # 清理旧版 token
        self._clear_legacy_authtokens()

    def start(self, host: str, port: int, *, timeout: float = 30.0) -> TunnelInfo:
        self._host = host
        self._port = port
        self._startup_timeout = timeout

        target_url = _local_tunnel_target(host, port)

        # 检查是否已有现有隧道
        existing = _find_existing_public_url(target_url, self._api_url)
        if existing is not None:
            self._reused = True
            self._public_url = existing
            LOG.info("reusing existing ngrok tunnel: %s", existing)
            return TunnelInfo(
                public_url=existing,
                provider=TunnelProviderType.NGROK,
                reused=True,
            )

        stop_ngrok_processes()

        ngrok_bin = self._find_ngrok_binary()
        config_path = self._ngrok_config_path()

        argv = [ngrok_bin, "http", target_url]
        if str(config_path):
            argv.append(f"--config={config_path.resolve().as_posix()}")
        if self._ngrok_url:
            argv.append(f"--url={self._ngrok_url}")

        self._stderr_handle = tempfile.SpooledTemporaryFile(max_size=65536)
        self._process = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_handle,
        )

        try:
            public_url = self._wait_for_public_url()
            self._public_url = public_url
            return TunnelInfo(
                public_url=public_url,
                provider=TunnelProviderType.NGROK,
                reused=False,
            )
        except Exception as exc:
            stderr = _read_ngrok_stderr(self._stderr_handle)
            combined = f"{exc}\n{stderr}" if stderr else str(exc)
            if _is_endpoint_already_online_error(combined):
                existing = _find_existing_public_url(target_url, self._api_url)
                if existing is not None:
                    self._reused = True
                    self._public_url = existing
                    LOG.info("reusing ngrok tunnel after endpoint conflict: %s", existing)
                    return TunnelInfo(
                        public_url=existing,
                        provider=TunnelProviderType.NGROK,
                        reused=True,
                    )
            self.stop()
            if stderr:
                raise RuntimeError(f"{exc}\n{stderr}") from exc
            raise

    def stop(self) -> None:
        if self._reused:
            self._reused = False
            return
        if self._process is None or self._process.poll() is not None:
            self._stderr_handle = None
            return
        LOG.info("stopping ngrok tunnel")
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=5)
        self._stderr_handle = None
        self._public_url = None

    def is_running(self) -> bool:
        if self._reused:
            return True
        return self._process is not None and self._process.poll() is None

    def validate_config(self) -> bool:
        config_path = self._ngrok_config_path()
        return self._read_authtoken_from_file(config_path) is not None

    def diagnostic(self) -> ProviderDiagnostic:
        diag = ProviderDiagnostic(provider_name=self.provider_name())
        try:
            diag.version = self._check_ngrok_version()
        except Exception as exc:
            diag.ok = False
            diag.error = str(exc)
            return diag

        try:
            diag.extra["authtoken_configured"] = self.validate_config()
        except Exception as exc:
            diag.ok = False
            diag.error = str(exc)

        return diag

    # ------------------------------------------------------------------
    # ngrok 二进制查找
    # ------------------------------------------------------------------

    def _find_ngrok_binary(self) -> str:
        bundled = self._find_bundled_ngrok()
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

    def _find_bundled_ngrok(self) -> str | None:
        import sys
        repo_root = Path(__file__).resolve().parents[3]
        return find_bundled_ngrok(
            repo_root,
            frozen=bool(getattr(sys, "frozen", False)),
        )

    # ------------------------------------------------------------------
    # authtoken 管理
    # ------------------------------------------------------------------

    def _ngrok_config_path(self) -> Path:
        return ngrok_config_dir() / NGROK_CONFIG_FILE_NAME

    def _read_authtoken_from_file(self, config_file: Path) -> str | None:
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
            token = self._token_from_mapping(data)
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

    @staticmethod
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

    def _configure_authtoken(self, token: str, ngrok_bin: str) -> None:
        stripped = token.strip()
        if not stripped:
            raise ValueError("ngrok authtoken 不能为空")

        config_file = self._ngrok_config_path()
        stop_ngrok_processes()

        # 修复 v3 配置
        if config_file.is_file():
            try:
                content = config_file.read_text(encoding="utf-8")
                data = yaml.safe_load(content)
                if isinstance(data, dict) and str(data.get("version", "")).strip().strip('"').strip("'") == "3":
                    if "authtoken" in data:
                        del data["authtoken"]
                        config_file.write_text(
                            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                            encoding="utf-8",
                        )
            except (OSError, yaml.YAMLError):
                pass

        config_file.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                ngrok_bin,
                "config",
                "add-authtoken",
                stripped,
                f"--config={config_file.resolve().as_posix()}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"ngrok authtoken 配置失败（退出码 {result.returncode}）:\n{stderr}"
            )

        # 等待写入
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            saved = self._read_authtoken_from_file(config_file)
            if saved == stripped:
                return
            time.sleep(0.1)

        raise RuntimeError("ngrok authtoken 未成功写入配置文件")

    def _verify_authtoken_connectivity(self, ngrok_bin: str, timeout: float = 8.0) -> None:
        config_file = self._ngrok_config_path()
        authtoken = self._read_authtoken_from_file(config_file)
        if not authtoken:
            raise RuntimeError("ngrok authtoken 未写入配置文件，无法验证连通性")

        stop_ngrok_processes()

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

        probe_port = random.randint(20000, 40000)
        target = f"127.0.0.1:{probe_port}"

        proc = subprocess.Popen(
            [
                ngrok_bin,
                "http",
                target,
                f"--config={probe_file.resolve().as_posix()}",
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
                        lowered = output.lower()
                        if "started tunnel" in lowered or "tunnel session started" in lowered or "starting web service" in lowered:
                            return
                        if "authentication failed" in lowered:
                            raise RuntimeError(output.strip())
                        if "err_ngrok_" in lowered:
                            if _is_endpoint_already_online_error(output):
                                if "started tunnel" in lowered or "tunnel session started" in lowered or "starting web service" in lowered:
                                    return
                            raise RuntimeError(output.strip())

                if proc.poll() is not None:
                    output = "".join(collected)
                    if proc.stdout is not None:
                        output += proc.stdout.read()
                    if "started tunnel" in output.lower() or "tunnel session started" in output.lower() or "starting web service" in output.lower():
                        return
                    raise RuntimeError(output.strip() or "ngrok exited before authtoken verification completed")

                time.sleep(0.1)

            raise RuntimeError("Timed out verifying ngrok authtoken")
        finally:
            probe_file.unlink(missing_ok=True)
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)

    def _clear_legacy_authtokens(self) -> None:
        from ..ngrok_manager import legacy_ngrok_config_paths, clear_authtoken_from_file

        for legacy_path in legacy_ngrok_config_paths():
            try:
                clear_authtoken_from_file(legacy_path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 隧道生命周期
    # ------------------------------------------------------------------

    def _wait_for_public_url(self) -> str:
        deadline = time.monotonic() + self._startup_timeout
        last_error = "ngrok did not report a public URL"
        target_url = _local_tunnel_target(self._host, self._port)
        expected_addr = _normalize_tunnel_addr(target_url)

        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                stderr = _read_ngrok_stderr(self._stderr_handle)
                message = "ngrok exited before creating a tunnel"
                if stderr:
                    message = f"{message}: {stderr}"
                raise RuntimeError(message)

            payload = _fetch_ngrok_agent_payload(self._api_url)
            if payload is not None:
                for record in _ngrok_tunnel_records(payload):
                    addr = _tunnel_record_addr(record)
                    if addr is None:
                        continue
                    try:
                        if _normalize_tunnel_addr(addr) != expected_addr:
                            continue
                    except ValueError:
                        continue
                    public_url = _tunnel_record_public_url(record)
                    if public_url:
                        return public_url

                public_url = _parse_ngrok_public_url(payload)
                if public_url:
                    return public_url

            for api_url in _ngrok_agent_urls(self._api_url):
                try:
                    with urlopen(api_url, timeout=1) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    public_url = _parse_ngrok_public_url(payload)
                    if public_url:
                        return public_url
                except (OSError, URLError, json.JSONDecodeError) as exc:
                    last_error = str(exc)
            time.sleep(0.25)

        raise RuntimeError(f"Timed out waiting for ngrok tunnel: {last_error}")

    # ------------------------------------------------------------------
    # 诊断
    # ------------------------------------------------------------------

    def _check_ngrok_version(self) -> str:
        ngrok_bin = self._find_ngrok_binary()
        result = subprocess.run(
            [ngrok_bin, "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"无法获取 ngrok 版本: {result.stderr.strip()}")
        return result.stdout.strip().split("\n")[0]
