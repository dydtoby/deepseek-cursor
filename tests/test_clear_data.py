from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deepseek_cursor_proxy.clear_data import clear_local_data
from deepseek_cursor_proxy.config import ProxyConfig, populate_default_config_file
from deepseek_cursor_proxy.ngrok_manager import (
    clear_authtoken,
    has_authtoken_configured,
    ngrok_config_path,
)
from deepseek_cursor_proxy.reasoning_store import ReasoningStore


class ClearDataTests(unittest.TestCase):
    def test_clear_authtoken_removes_token_line(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "ngrok"
            config_dir.mkdir()
            config_file = config_dir / "ngrok.yml"
            config_file.write_text(
                'version: "2"\nauthtoken: test-token\nregion: us\n',
                encoding="utf-8",
            )

            original = ngrok_config_path
            try:
                import deepseek_cursor_proxy.ngrok_manager as ngrok_manager

                ngrok_manager.ngrok_config_path = lambda: config_file  # type: ignore[assignment]
                self.assertTrue(has_authtoken_configured())
                self.assertTrue(clear_authtoken())
                self.assertFalse(has_authtoken_configured())
                content = config_file.read_text(encoding="utf-8")
                self.assertIn("version:", content)
                self.assertIn("region: us", content)
                self.assertNotIn("authtoken:", content)
            finally:
                ngrok_manager.ngrok_config_path = original  # type: ignore[assignment]

    def test_clear_local_data_clears_token_and_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / ".deepseek-cursor-proxy"
            app_dir.mkdir()
            config_path = app_dir / "config.yaml"
            populate_default_config_file(config_path)

            ngrok_dir = Path(temp_dir) / "ngrok"
            ngrok_dir.mkdir()
            ngrok_file = ngrok_dir / "ngrok.yml"
            ngrok_file.write_text('authtoken: secret\n', encoding="utf-8")

            config = ProxyConfig.from_file(config_path)
            store = ReasoningStore(config.reasoning_content_path)
            store.put("key", "reasoning", {"role": "assistant"})
            store.close()

            import deepseek_cursor_proxy.ngrok_manager as ngrok_manager

            original = ngrok_manager.ngrok_config_path
            try:
                ngrok_manager.ngrok_config_path = lambda: ngrok_file  # type: ignore[assignment]
                result = clear_local_data(config=config)
            finally:
                ngrok_manager.ngrok_config_path = original  # type: ignore[assignment]

            self.assertTrue(result.ok)
            self.assertTrue(result.authtoken_cleared)
            self.assertEqual(result.cache_rows_cleared, 1)
            self.assertNotIn("authtoken:", ngrok_file.read_text(encoding="utf-8"))
            verify_store = ReasoningStore(config.reasoning_content_path)
            try:
                self.assertIsNone(verify_store.get("key"))
            finally:
                verify_store.close()


if __name__ == "__main__":
    unittest.main()
