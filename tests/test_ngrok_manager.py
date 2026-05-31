from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deepseek_cursor_proxy.ngrok_manager import (
    clear_authtoken_from_file,
    is_missing_authtoken_error,
    migrate_and_cleanup_legacy_tokens,
    read_authtoken,
    read_authtoken_from_file,
    repair_v3_config_file,
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

    def test_read_authtoken_from_file_supports_v3_agent_authtoken(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "ngrok.yml"
            config_file.write_text(
                'version: "3"\nagent:\n  authtoken: v3-token\n',
                encoding="utf-8",
            )
            self.assertEqual(read_authtoken_from_file(config_file), "v3-token")

    def test_repair_v3_config_file_removes_invalid_top_level_authtoken(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "ngrok.yml"
            config_file.write_text(
                'version: "3"\nauthtoken: stale\nagent:\n  authtoken: good\n',
                encoding="utf-8",
            )
            self.assertTrue(repair_v3_config_file(config_file))
            content = config_file.read_text(encoding="utf-8")
            self.assertNotIn("\nauthtoken:", content.split("agent:")[0])
            self.assertEqual(read_authtoken_from_file(config_file), "good")

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
            try:
                write_authtoken_to_config(config_file, "2abcdefghijklmnopqrstuvwxyz1234567890ABCD")
            except (FileNotFoundError, RuntimeError):
                self.skipTest("ngrok binary unavailable")
            self.assertEqual(
                read_authtoken_from_file(config_file),
                "2abcdefghijklmnopqrstuvwxyz1234567890ABCD",
            )
            content = config_file.read_text(encoding="utf-8")
            self.assertNotIn('\nauthtoken:', content.split("agent:")[0])

    def test_migrate_and_cleanup_legacy_tokens_moves_token_to_primary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            primary_dir = Path(temp_dir) / "local" / "ngrok"
            legacy_dir = Path(temp_dir) / ".ngrok2"
            primary_dir.mkdir(parents=True)
            legacy_dir.mkdir()
            primary_file = primary_dir / "ngrok.yml"
            legacy_file = legacy_dir / "ngrok.yml"
            legacy_file.write_text('authtoken: legacy-token\n', encoding="utf-8")

            import deepseek_cursor_proxy.ngrok_manager as ngrok_manager

            original_primary = ngrok_manager.ngrok_config_path
            original_legacy = ngrok_manager.legacy_ngrok_config_paths
            try:
                ngrok_manager.ngrok_config_path = lambda: primary_file  # type: ignore[assignment]
                ngrok_manager.legacy_ngrok_config_paths = lambda: [legacy_file]  # type: ignore[assignment]
                result = migrate_and_cleanup_legacy_tokens()
            finally:
                ngrok_manager.ngrok_config_path = original_primary  # type: ignore[assignment]
                ngrok_manager.legacy_ngrok_config_paths = original_legacy  # type: ignore[assignment]

            self.assertTrue(result.migrated_token)
            self.assertEqual(result.migrated_from, legacy_file)
            self.assertIn(legacy_file, result.cleared_paths)
            self.assertEqual(read_authtoken_from_file(primary_file), "legacy-token")
            self.assertIsNone(read_authtoken_from_file(legacy_file))

    def test_migrate_and_cleanup_legacy_tokens_clears_stale_copy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            primary_dir = Path(temp_dir) / "local" / "ngrok"
            legacy_dir = Path(temp_dir) / ".ngrok2"
            primary_dir.mkdir(parents=True)
            legacy_dir.mkdir()
            primary_file = primary_dir / "ngrok.yml"
            legacy_file = legacy_dir / "ngrok.yml"
            primary_file.write_text('authtoken: primary-token\n', encoding="utf-8")
            legacy_file.write_text('authtoken: stale-token\n', encoding="utf-8")

            import deepseek_cursor_proxy.ngrok_manager as ngrok_manager

            original_primary = ngrok_manager.ngrok_config_path
            original_legacy = ngrok_manager.legacy_ngrok_config_paths
            try:
                ngrok_manager.ngrok_config_path = lambda: primary_file  # type: ignore[assignment]
                ngrok_manager.legacy_ngrok_config_paths = lambda: [legacy_file]  # type: ignore[assignment]
                result = migrate_and_cleanup_legacy_tokens()
            finally:
                ngrok_manager.ngrok_config_path = original_primary  # type: ignore[assignment]
                ngrok_manager.legacy_ngrok_config_paths = original_legacy  # type: ignore[assignment]

            self.assertFalse(result.migrated_token)
            self.assertEqual(read_authtoken_from_file(primary_file), "primary-token")
            self.assertIsNone(read_authtoken_from_file(legacy_file))


if __name__ == "__main__":
    unittest.main()
