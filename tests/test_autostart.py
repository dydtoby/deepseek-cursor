"""Tests for Windows login autostart helpers."""

from __future__ import annotations

import sys
import unittest
from unittest import mock

from deepseek_cursor_proxy import autostart


class AutostartTests(unittest.TestCase):
    def test_unsupported_on_non_windows(self) -> None:
        if sys.platform == "win32":
            self.skipTest("non-Windows only")
        self.assertFalse(autostart.supports_login_autostart())
        self.assertFalse(autostart.is_login_autostart_enabled())
        ok, reason = autostart.set_login_autostart(True)
        self.assertFalse(ok)
        self.assertEqual(reason, "unsupported_platform")

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_set_and_clear_login_autostart(self) -> None:
        with mock.patch.object(
            autostart,
            "resolve_autostart_executable",
            return_value=autostart.default_installed_executable(),
        ):
            ok, _ = autostart.set_login_autostart(True)
            self.assertTrue(ok)
            self.assertTrue(autostart.is_login_autostart_enabled())
            ok, _ = autostart.set_login_autostart(False)
            self.assertTrue(ok)
            self.assertFalse(autostart.is_login_autostart_enabled())


if __name__ == "__main__":
    unittest.main()
