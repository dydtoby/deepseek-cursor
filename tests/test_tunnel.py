from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from deepseek_cursor_proxy.tunnel import (
    NgrokTunnel,
    find_existing_public_url,
    local_tunnel_target,
    ngrok_agent_urls,
    normalize_tunnel_addr,
    parse_ngrok_public_url,
)


class TunnelTests(unittest.TestCase):
    def test_local_tunnel_target_uses_loopback_for_wildcard_hosts(self) -> None:
        self.assertEqual(local_tunnel_target("0.0.0.0", 9000), "http://127.0.0.1:9000")
        self.assertEqual(local_tunnel_target("::", 9000), "http://127.0.0.1:9000")

    def test_local_tunnel_target_formats_ipv6_hosts(self) -> None:
        self.assertEqual(local_tunnel_target("::1", 9000), "http://[::1]:9000")

    def test_parse_ngrok_public_url_prefers_https(self) -> None:
        payload = {
            "tunnels": [
                {"public_url": "http://example.ngrok-free.app"},
                {"public_url": "https://example.ngrok-free.app"},
            ]
        }

        self.assertEqual(
            parse_ngrok_public_url(payload), "https://example.ngrok-free.app"
        )

    def test_parse_ngrok_public_url_supports_endpoint_api(self) -> None:
        payload = {"endpoints": [{"url": "https://example.ngrok-free.app"}]}

        self.assertEqual(
            parse_ngrok_public_url(payload), "https://example.ngrok-free.app"
        )

    def test_parse_ngrok_public_url_ignores_missing_tunnels(self) -> None:
        self.assertIsNone(parse_ngrok_public_url({"tunnels": []}))
        self.assertIsNone(parse_ngrok_public_url({}))

    def test_ngrok_agent_urls_use_current_api_then_legacy_fallback(self) -> None:
        self.assertEqual(
            ngrok_agent_urls("http://127.0.0.1:4040/api"),
            [
                "http://127.0.0.1:4040/api/endpoints",
                "http://127.0.0.1:4040/api/tunnels",
            ],
        )

    def test_normalize_tunnel_addr_treats_local_aliases_as_equivalent(self) -> None:
        self.assertEqual(
            normalize_tunnel_addr("http://127.0.0.1:9000"),
            normalize_tunnel_addr("http://localhost:9000"),
        )
        self.assertEqual(
            normalize_tunnel_addr("http://0.0.0.0:9000"),
            "127.0.0.1:9000",
        )

    @patch("deepseek_cursor_proxy.tunnel.fetch_ngrok_agent_payload")
    def test_find_existing_public_url_supports_endpoints_api(self, fetch_payload) -> None:
        fetch_payload.return_value = {
            "endpoints": [
                {
                    "url": "https://example.ngrok-free.app",
                    "upstream": {"url": "http://127.0.0.1:9000"},
                }
            ]
        }

        self.assertEqual(
            find_existing_public_url("http://127.0.0.1:9000"),
            "https://example.ngrok-free.app",
        )

    @patch("deepseek_cursor_proxy.tunnel.fetch_ngrok_agent_payload")
    def test_find_existing_public_url_matches_target(self, fetch_payload) -> None:
        fetch_payload.return_value = {
            "tunnels": [
                {
                    "public_url": "https://example.ngrok-free.app",
                    "config": {"addr": "http://127.0.0.1:9000"},
                }
            ]
        }

        self.assertEqual(
            find_existing_public_url("http://127.0.0.1:9000"),
            "https://example.ngrok-free.app",
        )

    @patch("deepseek_cursor_proxy.tunnel.fetch_ngrok_agent_payload")
    def test_ngrok_tunnel_reuses_existing_public_url(self, fetch_payload) -> None:
        fetch_payload.return_value = {
            "tunnels": [
                {
                    "public_url": "https://example.ngrok-free.app",
                    "config": {"addr": "http://127.0.0.1:9000"},
                }
            ]
        }

        tunnel = NgrokTunnel("http://127.0.0.1:9000")
        self.assertEqual(tunnel.start(), "https://example.ngrok-free.app")
        self.assertTrue(tunnel.reused_external)
        self.assertIsNone(tunnel.process)

    def test_ngrok_tunnel_appends_url_flag_when_configured(self) -> None:
        with patch(
            "deepseek_cursor_proxy.tunnel.find_existing_public_url", return_value=None
        ):
            with patch("deepseek_cursor_proxy.tunnel.stop_ngrok_processes"):
                with patch(
                    "deepseek_cursor_proxy.tunnel.ngrok_command_available",
                    return_value=True,
                ):
                    with patch(
                        "deepseek_cursor_proxy.tunnel.subprocess.Popen"
                    ) as popen:
                        popen.return_value = MagicMock(poll=lambda: None)
                        with patch.object(
                            NgrokTunnel,
                            "wait_for_public_url",
                            return_value="https://example.ngrok-free.app",
                        ):
                            tunnel = NgrokTunnel(
                                "http://127.0.0.1:9000",
                                ngrok_url="https://my.ngrok.dev",
                            )
                            tunnel.start()
                        popen.assert_called_once()
                        argv, _kwargs = popen.call_args
                        self.assertEqual(
                            argv[0],
                            [
                                "ngrok",
                                "http",
                                "http://127.0.0.1:9000",
                                "--url=https://my.ngrok.dev",
                            ],
                        )


if __name__ == "__main__":
    unittest.main()
