"""隧道提供商抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TunnelProviderType(Enum):
    """支持的隧道提供商类型。"""

    NGROK = "ngrok"
    CLOUDFLARE = "cloudflare"
    FRP = "frp"
    NONE = "none"


@dataclass
class ProviderConfig:
    """隧道提供商通用配置。"""

    provider: TunnelProviderType = TunnelProviderType.NONE
    # ngrok 专属
    ngrok_auth_token: str | None = None
    ngrok_url: str | None = None
    # Cloudflare 专属
    cloudflare_token: str | None = None
    # frp 专属
    frp_server_addr: str = ""
    frp_server_port: int = 7000
    frp_auth_token: str = ""
    frp_remote_port: int = 0  # 0 = 自动分配
    frp_protocol: str = "https"


@dataclass
class TunnelInfo:
    """隧道信息。"""

    public_url: str
    provider: TunnelProviderType
    reused: bool = False


@dataclass
class ProviderDiagnostic:
    """提供商诊断结果。"""

    ok: bool = True
    provider_name: str = ""
    version: str = ""
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class BaseTunnelProvider(ABC):
    """隧道提供商抽象基类。

    所有隧道提供商（ngrok、cloudflared、frp 等）必须实现此接口。
    """

    @staticmethod
    @abstractmethod
    def provider_type() -> TunnelProviderType:
        """返回提供商类型枚举。"""
        ...

    @staticmethod
    @abstractmethod
    def provider_name() -> str:
        """返回人类可读的提供商名称。"""
        ...

    @staticmethod
    @abstractmethod
    def provider_description() -> str:
        """返回提供商的简要描述。"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查该提供商的二进制文件是否可用。"""
        ...

    @abstractmethod
    def configure(self, config: ProviderConfig) -> None:
        """根据配置初始化提供商。"""
        ...

    @abstractmethod
    def start(self, host: str, port: int, *, timeout: float = 30.0) -> TunnelInfo:
        """启动隧道，返回隧道信息。

        Args:
            host: 本地代理绑定的主机地址。
            port: 本地代理监听的端口。
            timeout: 等待隧道建立的最大秒数。

        Returns:
            TunnelInfo: 包含公网 URL 等信息的隧道状态。
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """停止隧道。"""
        ...

    @abstractmethod
    def is_running(self) -> bool:
        """检查隧道是否正在运行。"""
        ...

    @abstractmethod
    def validate_config(self) -> bool:
        """验证当前配置是否有效。"""
        ...

    def diagnostic(self) -> ProviderDiagnostic:
        """运行自诊断，返回诊断信息。"""
        diag = ProviderDiagnostic(
            provider_name=self.provider_name(),
        )
        try:
            diag.ok = self.is_available()
        except Exception as exc:
            diag.ok = False
            diag.error = str(exc)
        return diag

    def ensure_configured(self, config: ProviderConfig) -> None:
        """确保提供商已配置（用于 GUI 引导流程）。"""
        if not self.validate_config():
            self.configure(config)


def create_provider(provider_type: TunnelProviderType) -> BaseTunnelProvider:
    """工厂函数：根据类型创建对应的隧道提供商实例。"""
    if provider_type == TunnelProviderType.NGROK:
        from .providers.ngrok_provider import NgrokProvider

        return NgrokProvider()
    if provider_type == TunnelProviderType.CLOUDFLARE:
        from .providers.cloudflare_provider import CloudflareTunnelProvider

        return CloudflareTunnelProvider()
    if provider_type == TunnelProviderType.FRP:
        from .providers.frp_provider import FrpProvider

        return FrpProvider()
    raise ValueError(f"不支持的隧道提供商类型: {provider_type}")


def list_available_providers() -> list[dict[str, Any]]:
    """列出所有可用的隧道提供商信息（供 GUI 展示）。"""
    providers = []
    for ptype in (TunnelProviderType.NGROK, TunnelProviderType.CLOUDFLARE, TunnelProviderType.FRP):
        try:
            provider = create_provider(ptype)
            available = provider.is_available()
        except Exception:
            available = False
        providers.append({
            "type": ptype.value,
            "name": ptype.name if available else f"{ptype.name} (未安装)",
            "available": available,
        })
    return providers
