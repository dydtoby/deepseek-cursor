from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from deepseek_cursor_proxy.ngrok_manager import read_authtoken_from_file
from deepseek_cursor_proxy.platform_support import (
    gui_fonts,
    legacy_ngrok_config_paths,
    ngrok_binary_name,
    ngrok_config_dir,
    portable_archive_suffix,
    pyinstaller_add_data_sep,
)


class PlatformSupportTests(unittest.TestCase):
    def test_ngrok_binary_name_on_windows(self) -> None:
        with patch.object(sys, "platform", "win32"):
            self.assertEqual(ngrok_binary_name(), "ngrok.exe")

    def test_ngrok_binary_name_on_unix(self) -> None:
        with patch.object(sys, "platform", "linux"):
            self.assertEqual(ngrok_binary_name(), "ngrok")

    def test_pyinstaller_sep(self) -> None:
        with patch.object(sys, "platform", "win32"):
            self.assertEqual(pyinstaller_add_data_sep(), ";")
        with patch.object(sys, "platform", "linux"):
            self.assertEqual(pyinstaller_add_data_sep(), ":")

    def test_ngrok_config_dir_darwin(self) -> None:
        with patch.object(sys, "platform", "darwin"):
            path = ngrok_config_dir()
            self.assertIn("Application Support", str(path))
            self.assertTrue(str(path).endswith("ngrok"))

    def test_read_v3_agent_authtoken(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "ngrok.yml"
            config_file.write_text(
                'version: "3"\nagent:\n  authtoken: agent-token\n',
                encoding="utf-8",
            )
            self.assertEqual(read_authtoken_from_file(config_file), "agent-token")

    def test_gui_fonts_has_required_keys(self) -> None:
        fonts = gui_fonts()
        for key in ("title", "heading", "body", "mono", "url", "small"):
            self.assertIn(key, fonts)

    def test_portable_archive_suffix(self) -> None:
        suffix = portable_archive_suffix()
        self.assertTrue("-" in suffix)

    def test_legacy_paths_exclude_primary(self) -> None:
        with patch.object(sys, "platform", "linux"):
            primary = ngrok_config_dir() / "ngrok.yml"
            legacy = legacy_ngrok_config_paths(primary)
            self.assertNotIn(primary, legacy)


if __name__ == "__main__":
    unittest.main()
