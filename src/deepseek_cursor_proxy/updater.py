from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .config import ProxyConfig

GITHUB_RELEASES_API = "https://api.github.com/repos/dydtoby/deepseek-cursor/releases"


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    name: str
    html_url: str
    prerelease: bool
    published_at: str


def parse_version(tag: str) -> tuple[int, int, int] | None:
    normalized = tag.strip().lower()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    parts = normalized.split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def current_version(config_version: str) -> tuple[int, int, int] | None:
    return parse_version(config_version)


def fetch_latest_release(config: ProxyConfig, timeout: float = 5.0) -> ReleaseInfo | None:
    endpoint = f"{GITHUB_RELEASES_API}/latest"
    if config.update_channel == "prerelease":
        endpoint = GITHUB_RELEASES_API

    try:
        with urlopen(endpoint, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError):
        return None

    if isinstance(payload, list):
        # prerelease channel: pick newest release entry
        for item in payload:
            info = _release_info(item)
            if info is not None:
                return info
        return None
    return _release_info(payload)


def _release_info(payload: Any) -> ReleaseInfo | None:
    if not isinstance(payload, dict):
        return None
    tag_name = payload.get("tag_name")
    name = payload.get("name")
    html_url = payload.get("html_url")
    prerelease = bool(payload.get("prerelease"))
    published_at = payload.get("published_at") or ""
    if not isinstance(tag_name, str) or not isinstance(name, str) or not isinstance(
        html_url, str
    ):
        return None
    return ReleaseInfo(
        tag_name=tag_name,
        name=name,
        html_url=html_url,
        prerelease=prerelease,
        published_at=published_at,
    )


def has_update(current_tag: str, latest_tag: str) -> bool:
    current = parse_version(current_tag)
    latest = parse_version(latest_tag)
    if current is None or latest is None:
        return False
    return latest > current
