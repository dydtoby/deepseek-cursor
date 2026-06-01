from __future__ import annotations

import unittest

from deepseek_cursor_proxy.config import ProxyConfig
from deepseek_cursor_proxy.updater import has_update, parse_version


class UpdaterTests(unittest.TestCase):
    def test_parse_version_supports_v_prefix(self) -> None:
        self.assertEqual(parse_version("v0.1.2"), (0, 1, 2))
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))
        self.assertIsNone(parse_version("latest"))

    def test_has_update_compares_semver(self) -> None:
        self.assertTrue(has_update("v0.1.2", "v0.1.3"))
        self.assertFalse(has_update("v0.1.2", "v0.1.2"))
        self.assertFalse(has_update("v0.1.3", "v0.1.2"))

    def test_update_channel_default(self) -> None:
        self.assertEqual(ProxyConfig().update_channel, "stable")


if __name__ == "__main__":
    unittest.main()
