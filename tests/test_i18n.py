from __future__ import annotations

import unittest
from unittest.mock import patch

from deepseek_cursor_proxy.i18n import (
    SUPPORTED_LOCALES,
    detect_system_locale,
    init_locale,
    set_locale,
    t,
)


class I18nTests(unittest.TestCase):
    def setUp(self) -> None:
        init_locale()

    def test_supported_locales(self) -> None:
        self.assertIn("zh-CN", SUPPORTED_LOCALES)
        self.assertIn("en-US", SUPPORTED_LOCALES)

    def test_translate_known_key(self) -> None:
        set_locale("en-US", persist=False)
        self.assertEqual(t("dashboard.btn.start"), "Start Proxy")
        set_locale("zh-CN", persist=False)
        self.assertEqual(t("dashboard.btn.start"), "启动代理")

    def test_translate_with_format(self) -> None:
        set_locale("en-US", persist=False)
        self.assertIn(
            "deepseek-v4-pro",
            t("proxy.log.default_model", model="deepseek-v4-pro"),
        )

    @patch("deepseek_cursor_proxy.i18n.load_saved_locale", return_value=None)
    @patch("deepseek_cursor_proxy.i18n.detect_system_locale", return_value="en-US")
    def test_init_locale_falls_back_to_system(self, _detect, _saved) -> None:
        self.assertEqual(init_locale(), "en-US")


if __name__ == "__main__":
    unittest.main()
