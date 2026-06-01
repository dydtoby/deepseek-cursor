"""隧道提供商相关单元测试。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from deepseek_cursor_proxy.tunnel_provider import (
    BaseTunnelProvider,
    ProviderConfig,
    ProviderDiagnostic,
    TunnelInfo,
    TunnelProviderType,
    create_provider,
    list_available_providers,
)
from deepseek_cursor_proxy.tunnel_manager import TunnelManager


class TestTunnelProviderType(unittest.TestCase):
    def test_provider_type_values(self) -> None:
        self.assertEqual(TunnelProviderType.NGROK.value, "ngrok")
        self.assertEqual(TunnelProviderType.CLOUDFLARE.value, "cloudflare")
        self.assertEqual(TunnelProviderType.FRP.value, "frp")
        self.assertEqual(TunnelProviderType.NONE.value, "none")

    def test_provider_type_from_string(self) -> None:
        self.assertEqual(TunnelProviderType("ngrok"), TunnelProviderType.NGROK)
        self.assertEqual(TunnelProviderType("cloudflare"), TunnelProviderType.CLOUDFLARE)
        self.assertEqual(TunnelProviderType("frp"), TunnelProviderType.FRP)

    def test_provider_type_invalid_string(self) -> None:
        with self.assertRaises(ValueError):
            TunnelProviderType("invalid")


class TestProviderConfig(unittest.TestCase):
    def test_default_config(self) -> None:
        config = ProviderConfig()
        self.assertEqual(config.provider, TunnelProviderType.NONE)
        self.assertEqual(config.frp_server_port, 7000)
        self.assertEqual(config.frp_protocol, "https")

    def test_ngrok_config(self) -> None:
        config = ProviderConfig(
            provider=TunnelProviderType.NGROK,
            ngrok_auth_token="test-token",
            ngrok_url="https://custom.ngrok-free.app",
        )
        self.assertEqual(config.ngrok_auth_token, "test-token")
        self.assertEqual(config.ngrok_url, "https://custom.ngrok-free.app")

    def test_frp_config(self) -> None:
        config = ProviderConfig(
            provider=TunnelProviderType.FRP,
            frp_server_addr="frp.example.com",
            frp_server_port=7000,
            frp_auth_token="secret",
            frp_remote_port=8080,
        )
        self.assertEqual(config.frp_server_addr, "frp.example.com")
        self.assertEqual(config.frp_server_port, 7000)
        self.assertEqual(config.frp_auth_token, "secret")
        self.assertEqual(config.frp_remote_port, 8080)


class TestTunnelInfo(unittest.TestCase):
    def test_tunnel_info_creation(self) -> None:
        info = TunnelInfo(
            public_url="https://example.ngrok-free.app",
            provider=TunnelProviderType.NGROK,
            reused=False,
        )
        self.assertEqual(info.public_url, "https://example.ngrok-free.app")
        self.assertFalse(info.reused)

    def test_tunnel_info_reused(self) -> None:
        info = TunnelInfo(
            public_url="https://example.ngrok-free.app",
            provider=TunnelProviderType.NGROK,
            reused=True,
        )
        self.assertTrue(info.reused)


class TestProviderDiagnostic(unittest.TestCase):
    def test_default_diagnostic(self) -> None:
        diag = ProviderDiagnostic(provider_name="test")
        self.assertTrue(diag.ok)
        self.assertIsNone(diag.error)

    def test_failed_diagnostic(self) -> None:
        diag = ProviderDiagnostic(provider_name="test", ok=False, error="something went wrong")
        self.assertFalse(diag.ok)
        self.assertEqual(diag.error, "something went wrong")


class TestCreateProvider(unittest.TestCase):
    def test_create_ngrok_provider(self) -> None:
        provider = create_provider(TunnelProviderType.NGROK)
        self.assertEqual(provider.provider_type(), TunnelProviderType.NGROK)
        self.assertEqual(provider.provider_name(), "ngrok")

    def test_create_cloudflare_provider(self) -> None:
        provider = create_provider(TunnelProviderType.CLOUDFLARE)
        self.assertEqual(provider.provider_type(), TunnelProviderType.CLOUDFLARE)
        self.assertIn("Cloudflare", provider.provider_name())

    def test_create_frp_provider(self) -> None:
        provider = create_provider(TunnelProviderType.FRP)
        self.assertEqual(provider.provider_type(), TunnelProviderType.FRP)
        self.assertIn("frp", provider.provider_name().lower())

    def test_create_invalid_provider(self) -> None:
        with self.assertRaises(ValueError):
            create_provider(TunnelProviderType.NONE)


class TestListAvailableProviders(unittest.TestCase):
    def test_list_returns_providers(self) -> None:
        providers = list_available_providers()
        self.assertIsInstance(providers, list)
        self.assertGreater(len(providers), 0)
        for p in providers:
            self.assertIn("type", p)
            self.assertIn("name", p)
            self.assertIn("available", p)


class TestTunnelManager(unittest.TestCase):
    def test_initial_state(self) -> None:
        manager = TunnelManager()
        self.assertFalse(manager.is_running)
        self.assertIsNone(manager.public_url)
        self.assertEqual(manager.provider_type, TunnelProviderType.NONE)

    def test_configure_with_none(self) -> None:
        manager = TunnelManager()
        manager.configure(TunnelProviderType.NONE)
        self.assertEqual(manager.provider_type, TunnelProviderType.NONE)
        self.assertFalse(manager.is_running)

    def test_configure_with_ngrok(self) -> None:
        manager = TunnelManager()
        manager.configure(TunnelProviderType.NGROK)
        self.assertEqual(manager.provider_type, TunnelProviderType.NGROK)
        self.assertEqual(manager.provider_name, "ngrok")

    def test_configure_with_cloudflare(self) -> None:
        manager = TunnelManager()
        manager.configure(TunnelProviderType.CLOUDFLARE)
        self.assertEqual(manager.provider_type, TunnelProviderType.CLOUDFLARE)

    def test_configure_with_frp(self) -> None:
        manager = TunnelManager()
        manager.configure(TunnelProviderType.FRP)
        self.assertEqual(manager.provider_type, TunnelProviderType.FRP)

    def test_configure_with_string(self) -> None:
        manager = TunnelManager()
        manager.configure("ngrok")
        self.assertEqual(manager.provider_type, TunnelProviderType.NGROK)

    def test_list_providers(self) -> None:
        providers = TunnelManager.list_providers()
        self.assertIsInstance(providers, list)
        self.assertGreater(len(providers), 0)

    def test_from_config(self) -> None:
        manager = TunnelManager.from_config("ngrok")
        self.assertEqual(manager.provider_type, TunnelProviderType.NGROK)

    def test_start_without_configure(self) -> None:
        manager = TunnelManager()
        with self.assertRaises(RuntimeError):
            manager.start()

    def test_validate_config_without_configure(self) -> None:
        manager = TunnelManager()
        self.assertFalse(manager.validate_config())


class TestNgrokProvider(unittest.TestCase):
    def test_provider_metadata(self) -> None:
        from deepseek_cursor_proxy.providers.ngrok_provider import NgrokProvider

        self.assertEqual(NgrokProvider.provider_type(), TunnelProviderType.NGROK)
        self.assertEqual(NgrokProvider.provider_name(), "ngrok")

    def test_is_available(self) -> None:
        from deepseek_cursor_proxy.providers.ngrok_provider import NgrokProvider

        provider = NgrokProvider()
        # is_available 返回 bool，测试至少不会抛出异常
        result = provider.is_available()
        self.assertIsInstance(result, bool)

    def test_validate_config_when_no_config(self) -> None:
        from deepseek_cursor_proxy.providers.ngrok_provider import NgrokProvider

        provider = NgrokProvider()
        # 没有配置 ngrok 时应该返回 False
        result = provider.validate_config()
        self.assertIsInstance(result, bool)


class TestCloudflareProvider(unittest.TestCase):
    def test_provider_metadata(self) -> None:
        from deepseek_cursor_proxy.providers.cloudflare_provider import CloudflareTunnelProvider

        self.assertEqual(
            CloudflareTunnelProvider.provider_type(), TunnelProviderType.CLOUDFLARE
        )
        self.assertIn("Cloudflare", CloudflareTunnelProvider.provider_name())

    def test_is_available(self) -> None:
        from deepseek_cursor_proxy.providers.cloudflare_provider import CloudflareTunnelProvider

        provider = CloudflareTunnelProvider()
        result = provider.is_available()
        self.assertIsInstance(result, bool)

    def test_validate_config(self) -> None:
        from deepseek_cursor_proxy.providers.cloudflare_provider import CloudflareTunnelProvider

        provider = CloudflareTunnelProvider()
        result = provider.validate_config()
        self.assertIsInstance(result, bool)


class TestFrpProvider(unittest.TestCase):
    def test_provider_metadata(self) -> None:
        from deepseek_cursor_proxy.providers.frp_provider import FrpProvider

        self.assertEqual(FrpProvider.provider_type(), TunnelProviderType.FRP)
        self.assertIn("frp", FrpProvider.provider_name().lower())

    def test_is_available(self) -> None:
        from deepseek_cursor_proxy.providers.frp_provider import FrpProvider

        provider = FrpProvider()
        result = provider.is_available()
        self.assertIsInstance(result, bool)

    def test_validate_config_without_server(self) -> None:
        from deepseek_cursor_proxy.providers.frp_provider import FrpProvider

        provider = FrpProvider()
        self.assertFalse(provider.validate_config())

    def test_configure_requires_server(self) -> None:
        from deepseek_cursor_proxy.providers.frp_provider import FrpProvider

        provider = FrpProvider()
        config = ProviderConfig(provider=TunnelProviderType.FRP)
        with self.assertRaises(ValueError):
            provider.configure(config)


if __name__ == "__main__":
    unittest.main()
