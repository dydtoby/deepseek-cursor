"""PyInstaller 打包入口 — 使用绝对导入，避免相对导入错误。"""

from __future__ import annotations

import sys

from deepseek_cursor_proxy.app import main

if __name__ == "__main__":
    sys.exit(main())
