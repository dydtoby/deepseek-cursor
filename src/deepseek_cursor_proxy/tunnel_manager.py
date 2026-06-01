"""统一隧道管理器 — 封装多隧道提供商切换。

提供简洁的 start/stop/is_running 接口，对 GUI 和 CLI 透明。
"""

from __future__ import annotations

from typing import Any

from .tunnel_provider import (
    BaseTunnelProvider,
    create_provider,
    ProviderConfig,
    ProviderDiagnostic,
    TunnelInfo,
    TunnelProviderType,
)
from .logging import LOG


class TunnelManager:
    """统一隧道管理器。

    用法：
        manager = TunnelManager()
        manager.configure(provider_type=..., config=...)
        info = manager.start(host="127.0.0.1", port=9000)
        # info.public_url 即为公网 URL
        manager.stop()
    """

    def __init__(self) -> None:
        self._provider: BaseTunnelProvider | None = None
        self._provider_type: TunnelProviderType = TunnelProviderType.NONE
        self._provider_config: ProviderConfig = ProviderConfig()
        self._info: TunnelInfo | None = None

    # ------------------------------------------------------------------
    # 公共属性
    # ------------------------------------------------------------------

    @property
    def public_url(self) -> str | None:
        if self._info is not None:
            return self._info.public_url
        return None

    @property
    def is_running(self) -> bool:
        return self._provider is not None and self._provider.is_running()

    @property
    def provider_type(self) -> TunnelProviderType:
        return self._provider_type

    @property
    def provider_name(self) -> str:
        if self._provider is not None:
            return self._provider.provider_name()
        return "无"

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    def configure(
        self,
        provider_type: TunnelProviderType | str,
        config: ProviderConfig | None = None,
    ) -> None:
        """配置隧道管理器。

        Args:
            provider_type: 隧道提供商类型 ("ngrok", "cloudflare", "frp", "none")。
            config: 提供商配置。
        """
        if isinstance(provider_type, str):
            provider_type = TunnelProviderType(provider_type)

        if provider_type == TunnelProviderType.NONE:
            self._provider = None
            self._provider_type = TunnelProviderType.NONE
            return

        self._provider_type = provider_type
        self._provider_config = config or ProviderConfig(provider=provider_type)
        self._provider = create_provider(provider_type)

    def ensure_authtoken(self, token: str) -> None:
        """确保 ngrok authtoken 已配置（向后兼容，仅适用于 ngrok 提供商）。"""
        if self._provider is None:
            return

        config = ProviderConfig(
            provider=self._provider_type,
            ngrok_auth_token=token,
        )
        self._provider.ensure_configured(config)

    # ------------------------------------------------------------------
    # 隧道生命周期
    # ------------------------------------------------------------------

    def start(
        self,
        host: str = "127.0.0.1",
        port: int = 9000,
        *,
        timeout: float = 30.0,
    ) -> str:
        """启动隧道，返回公网 HTTPS URL。

        Raises:
            RuntimeError: 提供商不可用或启动失败。
        """
        if self._provider is None:
            raise RuntimeError("隧道提供商未配置。请先调用 configure()。")

        if not self._provider.is_available():
            raise RuntimeError(
                f"隧道提供商 {self._provider.provider_name()} 不可用。"
                "请确保已安装对应的客户端程序。"
            )

        try:
            self._info = self._provider.start(host, port, timeout=timeout)
            return self._info.public_url
        except Exception:
            raise

    def stop(self) -> None:
        """停止隧道。"""
        if self._provider is not None:
            self._provider.stop()
        self._info = None

    # ------------------------------------------------------------------
    # 诊断
    # ------------------------------------------------------------------

    def diagnostic(self) -> ProviderDiagnostic | None:
        if self._provider is not None:
            return self._provider.diagnostic()
        return None

    def validate_config(self) -> bool:
        if self._provider is not None:
            return self._provider.validate_config()
        return False

    # ------------------------------------------------------------------
    # 工厂 / 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def list_providers() -> list[dict[str, Any]]:
        """列出所有支持的提供商（供 GUI 展示）。"""
        providers = []
        for ptype in (TunnelProviderType.NGROK, TunnelProviderType.CLOUDFLARE, TunnelProviderType.FRP):
            try:
                provider = create_provider(ptype)
                available = provider.is_available()
                providers.append({
                    "type": ptype.value,
                    "name": provider.provider_name(),
                    "description": provider.provider_description(),
                    "available": available,
                })
            except Exception:
                providers.append({
                    "type": ptype.value,
                    "name": ptype.name,
                    "description": "",
                    "available": False,
                })
        return providers

    @classmethod
    def from_config(cls, tunnel_provider: str, config: ProviderConfig | None = None) -> "TunnelManager":
        """从配置创建 TunnelManager 实例。"""
        manager = cls()
        manager.configure(tunnel_provider, config)
        return manager
