"""DeepSeek Cursor Proxy 统一入口。

支持两种模式：
  CLI 模式（默认，在终端中运行）
  GUI 模式（PyInstaller 打包后双击启动，或使用 --gui 标志）
"""

from __future__ import annotations

import argparse
import sys


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DeepSeek Cursor Proxy — 桌面应用程序 / 命令行工具"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="以命令行模式运行",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="以图形界面模式运行",
    )
    # 以下参数仅在 CLI 模式下有效，由 server.main() 处理
    parser.add_argument(
        "--config",
        dest="config_path",
        type=str,
        help="YAML 配置文件路径",
    )
    parser.add_argument("--host", help="绑定地址")
    parser.add_argument("--port", type=int, help="绑定端口")
    parser.add_argument("--model", help="默认 DeepSeek 模型")
    parser.add_argument("--base-url", help="DeepSeek API 基础 URL")
    parser.add_argument(
        "--no-ngrok", action="store_true", help="不使用 ngrok 隧道"
    )
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    return parser


def _is_frozen() -> bool:
    """检查是否为 PyInstaller 打包的可执行文件。"""
    return getattr(sys, "frozen", False)


def _is_terminal() -> bool:
    """检查是否在终端中运行。"""
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _is_gui_desired(raw_argv: list[str]) -> bool:
    """判断是否应启动 GUI 模式。

    优先级：
    1. --gui → 强制 GUI
    2. --cli → 强制 CLI
    3. PyInstaller 打包（非终端）→ GUI
    4. 终端中运行 → CLI
    """
    if "--gui" in raw_argv:
        return True
    if "--cli" in raw_argv:
        return False
    if _is_frozen() and not _is_terminal():
        return True
    # 默认 CLI（保持向后兼容）
    return False


def main(argv: list[str] | None = None) -> int:
    """主入口：根据运行环境决定启动 GUI 还是 CLI。"""
    raw_argv = argv if argv is not None else sys.argv[1:]

    if _is_gui_desired(raw_argv):
        from deepseek_cursor_proxy.gui import run_gui

        run_gui()
        return 0

    # CLI 模式：过滤掉 --gui 标志，其余参数传给 server.main()
    filtered = [arg for arg in raw_argv if arg not in {"--gui", "--cli"}]
    from deepseek_cursor_proxy.server import main as server_main

    return server_main(filtered if filtered else None)


if __name__ == "__main__":
    sys.exit(main())
