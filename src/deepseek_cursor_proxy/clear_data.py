"""清除本地缓存与隧道凭证。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import ProxyConfig, update_config_file
from .ngrok_manager import clear_authtoken, has_authtoken_configured, stop_ngrok_processes
from .reasoning_store import ReasoningStore


@dataclass(frozen=True)
class ClearDataResult:
    authtoken_cleared: bool
    cache_rows_cleared: int
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def clear_local_data(
    *,
    clear_token: bool = True,
    clear_reasoning_cache: bool = True,
    config: ProxyConfig | None = None,
) -> ClearDataResult:
    """清除隧道凭证与推理缓存。

    对于 ngrok 提供商：清除 ngrok 配置文件中的 authtoken。
    对于 cloudflare/frp 提供商：清除配置文件中的对应 token 字段。
    """
    errors: list[str] = []
    authtoken_cleared = False
    cache_rows_cleared = 0

    if clear_token:
        try:
            resolved = config or ProxyConfig.from_file()
            provider = resolved.tunnel_provider

            if provider in ("cloudflare", "frp"):
                token_key = "cloudflare_token" if provider == "cloudflare" else "frp_auth_token"
                update_config_file({token_key: None})
                authtoken_cleared = True

            # ngrok 凭证：当前使用 ngrok，或存在遗留 authtoken 时一并清除
            if provider == "ngrok" or has_authtoken_configured():
                stop_ngrok_processes()
                if clear_authtoken():
                    authtoken_cleared = True
        except OSError as exc:
            errors.append(str(exc))

    if clear_reasoning_cache:
        try:
            resolved = config or ProxyConfig.from_file()
            cache_path = resolved.reasoning_content_path
            if cache_path.is_file():
                store = ReasoningStore(
                    cache_path,
                    max_age_seconds=resolved.reasoning_cache_max_age_seconds,
                    max_rows=resolved.reasoning_cache_max_rows,
                )
                cache_rows_cleared = store.clear()
                store.close()
        except Exception as exc:
            errors.append(str(exc))

    return ClearDataResult(
        authtoken_cleared=authtoken_cleared,
        cache_rows_cleared=cache_rows_cleared,
        errors=errors,
    )


def has_stored_credentials() -> bool:
    """检查是否存在已保存的隧道凭证。"""
    return has_authtoken_configured()
