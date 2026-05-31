from __future__ import annotations

from dataclasses import dataclass, field
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import URLError
from urllib.request import urlopen

from .logging import LOG


DEFAULT_NGROK_API_URL = "http://127.0.0.1:4040/api"


def local_tunnel_target(host: str, port: int) -> str:
    local_host = host.strip() or "127.0.0.1"
    if local_host in {"0.0.0.0", "::"}:
        local_host = "127.0.0.1"
    if ":" in local_host and not local_host.startswith("["):
        local_host = f"[{local_host}]"
    return f"http://{local_host}:{port}"


def parse_ngrok_public_url(payload: dict[str, Any]) -> str | None:
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


def ngrok_agent_urls(api_url: str) -> list[str]:
    normalized = api_url.rstrip("/")
    if normalized.endswith("/endpoints") or normalized.endswith("/tunnels"):
        return [normalized]
    return [f"{normalized}/endpoints", f"{normalized}/tunnels"]


def normalize_tunnel_addr(addr: str) -> str:
    """Normalize tunnel addresses for comparison (host aliases, scheme, brackets)."""
    normalized = addr.strip()
    if normalized.startswith("http://"):
        normalized = normalized[len("http://") :]
    elif normalized.startswith("https://"):
        normalized = normalized[len("https://") :]

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


def tunnel_record_addr(record: dict[str, Any]) -> str | None:
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


def tunnel_record_public_url(record: dict[str, Any]) -> str | None:
    for key in ("url", "public_url"):
        value = record.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def ngrok_tunnel_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("endpoints")
    if not isinstance(records, list):
        records = payload.get("tunnels")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def fetch_ngrok_agent_payload(api_url: str = DEFAULT_NGROK_API_URL) -> dict[str, Any] | None:
    for endpoint in ngrok_agent_urls(api_url):
        try:
            with urlopen(endpoint, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def find_existing_public_url(
    target_url: str,
    api_url: str = DEFAULT_NGROK_API_URL,
) -> str | None:
    """Return an existing ngrok public URL if one already forwards to target_url."""
    try:
        expected_addr = normalize_tunnel_addr(target_url)
    except ValueError:
        return None

    payload = fetch_ngrok_agent_payload(api_url)
    if payload is None:
        return None

    https_url: str | None = None
    http_url: str | None = None
    for record in ngrok_tunnel_records(payload):
        addr = tunnel_record_addr(record)
        if addr is None:
            continue
        try:
            if normalize_tunnel_addr(addr) != expected_addr:
                continue
        except ValueError:
            continue

        public_url = tunnel_record_public_url(record)
        if public_url is None:
            continue
        if public_url.startswith("https://"):
            return public_url
        if http_url is None:
            http_url = public_url

    return https_url or http_url


def read_ngrok_stderr(stderr_handle: BinaryIO | None) -> str:
    if stderr_handle is None:
        return ""
    try:
        stderr_handle.seek(0)
        text = stderr_handle.read().decode("utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return ""
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def ngrok_command_available(command: str) -> bool:
    if Path(command).is_file():
        return True
    return shutil.which(command) is not None


@dataclass
class NgrokTunnel:
    target_url: str
    ngrok_url: str | None = None
    command: str = "ngrok"
    api_url: str = DEFAULT_NGROK_API_URL
    startup_timeout: float = 15.0

    process: subprocess.Popen[bytes] | None = None
    stderr_handle: tempfile.SpooledTemporaryFile[bytes] | None = field(
        default=None, repr=False
    )
    reused_external: bool = False

    def start(self) -> str:
        existing = find_existing_public_url(self.target_url, self.api_url)
        if existing is not None:
            self.reused_external = True
            LOG.info("reusing existing ngrok tunnel: %s", existing)
            return existing

        if not ngrok_command_available(self.command):
            raise RuntimeError(
                "ngrok is not installed or is not on PATH. Install it, then run "
                "`ngrok config add-authtoken <token>` once."
            )

        argv = [self.command, "http", self.target_url]
        if self.ngrok_url:
            argv.append(f"--url={self.ngrok_url}")

        self.stderr_handle = tempfile.SpooledTemporaryFile(max_size=65536)
        self.process = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=self.stderr_handle,
        )
        try:
            return self.wait_for_public_url()
        except Exception as exc:
            stderr = read_ngrok_stderr(self.stderr_handle)
            self.stop()
            if stderr:
                raise RuntimeError(f"{exc}\n{stderr}") from exc
            raise

    def wait_for_public_url(self) -> str:
        deadline = time.monotonic() + self.startup_timeout
        last_error = "ngrok did not report a public URL"
        expected_addr = normalize_tunnel_addr(self.target_url)
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                stderr = read_ngrok_stderr(self.stderr_handle)
                message = "ngrok exited before creating a tunnel"
                if stderr:
                    message = f"{message}: {stderr}"
                raise RuntimeError(message)

            payload = fetch_ngrok_agent_payload(self.api_url)
            if payload is not None:
                for record in ngrok_tunnel_records(payload):
                    addr = tunnel_record_addr(record)
                    if addr is None:
                        continue
                    try:
                        if normalize_tunnel_addr(addr) != expected_addr:
                            continue
                    except ValueError:
                        continue
                    public_url = tunnel_record_public_url(record)
                    if public_url:
                        return public_url

                public_url = parse_ngrok_public_url(payload)
                if public_url:
                    return public_url

            for api_url in ngrok_agent_urls(self.api_url):
                try:
                    with urlopen(api_url, timeout=1) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    public_url = parse_ngrok_public_url(payload)
                    if public_url:
                        return public_url
                except (OSError, URLError, json.JSONDecodeError) as exc:
                    last_error = str(exc)
            time.sleep(0.25)
        raise RuntimeError(f"Timed out waiting for ngrok tunnel: {last_error}")

    def stop(self) -> None:
        if self.reused_external:
            self.reused_external = False
            return
        if self.process is None or self.process.poll() is not None:
            self.stderr_handle = None
            return
        LOG.info("stopping ngrok tunnel")
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.stderr_handle = None
