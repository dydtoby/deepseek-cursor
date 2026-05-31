from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deepseek_cursor_proxy.ngrok_manager import (
    clear_authtoken_from_file,
    is_missing_authtoken_error,
    read_authtoken,
    read_authtoken_from_file,
    write_authtoken_to_config,
)


class NgrokManagerTests(unittest.TestCase):
    def test_read_authtoken_from_file_supports_yaml_mapping(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "ngrok.yml"
            config_file.write_text(
                'version: "2"\nauthtoken: abc123\n',
                encoding="utf-8",
            )
            self.assertEqual(read_authtoken_from_file(config_file), "abc123")

    def test_clear_authtoken_from_file_removes_yaml_key(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "ngrok.yml"
            config_file.write_text(
                'version: "2"\nauthtoken: abc123\nregion: us\n',
                encoding="utf-8",
            )
            self.assertTrue(clear_authtoken_from_file(config_file))
            self.assertIsNone(read_authtoken_from_file(config_file))
            content = config_file.read_text(encoding="utf-8")
            self.assertIn("version:", content)
            self.assertIn("region: us", content)

    def test_is_missing_authtoken_error_detects_4018(self) -> None:
        message = (
            "authentication failed: Usage of ngrok requires a verified account "
            "and authtoken. ERR_NGROK_4018"
        )
        self.assertTrue(is_missing_authtoken_error(message))
        self.assertFalse(is_missing_authtoken_error("connection reset"))

    def test_read_authtoken_uses_primary_config_only(self) -> None:
        with TemporaryDirectory() as temp_dir:
            primary_dir = Path(temp_dir) / "local" / "ngrok"
            legacy_dir = Path(temp_dir) / ".ngrok2"
            primary_dir.mkdir(parents=True)
            legacy_dir.mkdir()
            primary_file = primary_dir / "ngrok.yml"
            legacy_file = legacy_dir / "ngrok.yml"
            primary_file.write_text('version: "2"\n', encoding="utf-8")
            legacy_file.write_text('authtoken: legacy-token\n', encoding="utf-8")

            import deepseek_cursor_proxy.ngrok_manager as ngrok_manager

            original = ngrok_manager.ngrok_config_path
            try:
                ngrok_manager.ngrok_config_path = lambda: primary_file  # type: ignore[assignment]
                self.assertIsNone(read_authtoken())
            finally:
                ngrok_manager.ngrok_config_path = original  # type: ignore[assignment]

    def test_write_authtoken_to_config_creates_yaml(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "ngrok" / "ngrok.yml"
            write_authtoken_to_config(config_file, "saved-token")
            self.assertEqual(read_authtoken_from_file(config_file), "saved-token")


if __name__ == "__main__":
    unittest.main()
