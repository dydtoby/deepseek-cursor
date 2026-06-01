"""DeepSeek Cursor Proxy GUI — tkinter 桌面应用。

包含：引导向导、主控制面板、实时日志、设置面板。
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from .clear_data import clear_local_data
from .config import (
    ProxyConfig,
    default_config_path,
    populate_default_config_file,
)
from . import __version__
from .i18n import SUPPORTED_LOCALES, get_locale, init_locale, set_locale, t
from .ngrok_manager import (
    NgrokTunnelManager,
    configure_authtoken,
    is_endpoint_already_online_error,
    find_ngrok_binary,
    has_authtoken_configured,
    is_missing_authtoken_error,
    migrate_and_cleanup_legacy_tokens,
    validate_authtoken,
)
from .server import DeepSeekProxyHandler, DeepSeekProxyServer
from .reasoning_store import ReasoningStore
from .platform_support import gui_fonts
from .tunnel import local_tunnel_target
from .updater import fetch_latest_release, has_update

LOG = logging.getLogger("deepseek_cursor_proxy.gui")

# ---------------------------------------------------------------------------
# 日志队列处理器：将日志转发到 tkinter GUI
# ---------------------------------------------------------------------------


class QueueLogHandler(logging.Handler):
    """将日志记录放入 queue.Queue，由 tkinter 定时轮询显示。"""

    def __init__(self, log_queue: queue.Queue[logging.LogRecord]) -> None:
        super().__init__()
        self._queue = log_queue
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self._queue.put(record)


# ---------------------------------------------------------------------------
# 代理控制器：后台线程管理代理服务器生命周期
# ---------------------------------------------------------------------------


class ProxyController:
    """在后台线程中管理代理服务器的启动/停止。"""

    def __init__(
        self,
        status_queue: queue.Queue[dict[str, Any]],
        log_queue: queue.Queue[logging.LogRecord],
    ) -> None:
        self._status_queue = status_queue
        self._log_queue = log_queue
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._server: DeepSeekProxyServer | None = None
        self._tunnel_manager: NgrokTunnelManager | None = None
        self._store: ReasoningStore | None = None

    def start(self, config: ProxyConfig) -> None:
        """启动代理服务器和 ngrok 隧道。"""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, args=(config,), daemon=True, name="proxy-controller"
        )
        self._thread.start()

    def stop(self) -> None:
        """停止代理服务器和 ngrok 隧道。"""
        self._stop_event.set()
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
        if self._tunnel_manager is not None:
            try:
                self._tunnel_manager.stop()
            except Exception:
                pass
        if self._store is not None:
            try:
                self._store.close()
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _emit_status(self, **kwargs: Any) -> None:
        self._status_queue.put(kwargs)

    def _run(self, config: ProxyConfig) -> None:
        try:
            self._emit_status(state="starting", message=t("proxy.init_cache"))

            self._store = ReasoningStore(
                config.reasoning_content_path,
                max_age_seconds=config.reasoning_cache_max_age_seconds,
                max_rows=config.reasoning_cache_max_rows,
            )

            self._emit_status(state="starting", message=t("proxy.start_local"))

            self._server = DeepSeekProxyServer(
                (config.host, config.port), DeepSeekProxyHandler
            )
            self._server.config = config
            self._server.reasoning_store = self._store
            self._server.trace_writer = None

            server_thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="proxy-server",
            )
            server_thread.start()

            local_url = f"http://{config.host}:{config.port}/v1"

            if config.ngrok:
                self._emit_status(
                    state="starting", message=t("proxy.start_ngrok")
                )
                self._tunnel_manager = NgrokTunnelManager(
                    host=config.host,
                    port=config.port,
                    ngrok_url=config.ngrok_url,
                )
                try:
                    public_url = self._tunnel_manager.start()
                    self._emit_status(
                        state="running",
                        message=t("proxy.running"),
                        public_url=public_url,
                        local_url=local_url,
                    )
                    LOG.info(t("proxy.log.ngrok_url", url=public_url))
                    LOG.info(
                        t("proxy.log.cursor_base", url=f"{public_url.rstrip('/')}/v1")
                    )
                except Exception as exc:
                    error_text = str(exc)
                    if is_missing_authtoken_error(error_text):
                        error_text = t("proxy.ngrok_auth_missing")
                    self._emit_status(
                        state="error",
                        message=t("proxy.ngrok_failed", error=error_text),
                        local_url=local_url,
                    )
                    LOG.error(t("proxy.ngrok_failed", error=error_text))
                    LOG.info(t("proxy.log.local_running", url=local_url))
            else:
                self._emit_status(
                    state="running",
                    message=t("proxy.running_local"),
                    local_url=local_url,
                )
                LOG.info(t("proxy.log.local_url", url=local_url))

            LOG.info(t("proxy.log.default_model", model=config.upstream_model))
            LOG.info(t("proxy.log.cursor_hint"))

            # 等待停止信号
            while not self._stop_event.is_set():
                self._stop_event.wait(0.5)

        except Exception as exc:
            LOG.error(t("proxy.start_failed", error=exc))
            self._emit_status(
                state="error", message=t("proxy.start_failed", error=exc)
            )
        finally:
            self._cleanup()
            self._emit_status(state="stopped", message=t("proxy.stopped"))

    def _cleanup(self) -> None:
        if self._tunnel_manager is not None:
            try:
                self._tunnel_manager.stop()
            except Exception:
                pass
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            try:
                self._server.server_close()
            except Exception:
                pass
        if self._store is not None:
            try:
                self._store.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 色彩方案
# ---------------------------------------------------------------------------

COLORS = {
    "bg": "#1e1e2e",
    "fg": "#cdd6f4",
    "surface": "#313244",
    "surface_bright": "#45475a",
    "accent": "#89b4fa",
    "accent_dim": "#74c7ec",
    "green": "#a6e3a1",
    "yellow": "#f9e2af",
    "red": "#f38ba8",
    "text_dim": "#6c7086",
    "border": "#45475a",
}

FONTS = gui_fonts()


def apply_theme(root: tk.Tk) -> None:
    """为根窗口应用深色主题。"""
    root.configure(bg=COLORS["bg"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["fg"], font=FONTS["body"])
    style.configure("TButton", background=COLORS["surface_bright"], foreground=COLORS["fg"], font=FONTS["body"], borderwidth=0, focuscolor="none")
    style.map("TButton", background=[("active", COLORS["accent"]), ("disabled", COLORS["surface"])])
    style.configure("TEntry", fieldbackground=COLORS["surface"], foreground=COLORS["fg"], font=FONTS["body"], insertcolor=COLORS["fg"])
    style.configure("TCheckbutton", background=COLORS["bg"], foreground=COLORS["fg"], font=FONTS["body"])
    style.configure("TLabelframe", background=COLORS["bg"], foreground=COLORS["text_dim"], font=FONTS["body"])
    style.configure("TLabelframe.Label", background=COLORS["bg"], foreground=COLORS["text_dim"], font=FONTS["body"])


# ---------------------------------------------------------------------------
# 引导向导 — 首次运行配置
# ---------------------------------------------------------------------------


class SetupWizard(tk.Frame):
    """首次运行引导向导：配置 ngrok authtoken + API key。"""

    def __init__(
        self,
        master: tk.Widget,
        on_complete: Any,
        on_language_change: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, bg=COLORS["bg"], **kwargs)
        self._on_complete = on_complete
        self._on_language_change = on_language_change

        # 步骤控制
        self._current_step = 0
        self._steps: list[tk.Frame] = []
        self._token_var = tk.StringVar()
        self._api_key_var = tk.StringVar()

        self._build()

    def _build(self) -> None:
        # 标题
        header = tk.Frame(self, bg=COLORS["bg"])
        header.pack(fill="x", pady=(30, 10))
        tk.Label(
            header,
            text="DeepSeek Cursor Proxy",
            font=FONTS["title"],
            bg=COLORS["bg"],
            fg=COLORS["accent"],
        ).pack()
        tk.Label(
            header,
            text=t("wizard.subtitle"),
            font=FONTS["heading"],
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
        ).pack(pady=(2, 0))

        lang_frame = tk.Frame(header, bg=COLORS["bg"])
        lang_frame.pack(pady=(8, 0))
        tk.Label(
            lang_frame,
            text=f"{t('language.label')}: ",
            font=FONTS["small"],
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
        ).pack(side="left")
        self._language_var = tk.StringVar(value=get_locale())
        lang_combo = ttk.Combobox(
            lang_frame,
            textvariable=self._language_var,
            values=list(SUPPORTED_LOCALES),
            state="readonly",
            width=12,
        )
        lang_combo.pack(side="left")
        lang_combo.bind("<<ComboboxSelected>>", self._on_language_selected)

        # 步骤指示器
        self._step_indicator = tk.Frame(self, bg=COLORS["bg"])
        self._step_indicator.pack(fill="x", pady=(10, 5))

        # 内容区
        self._content = tk.Frame(self, bg=COLORS["bg"])
        self._content.pack(fill="both", expand=True, padx=40, pady=10)

        # 按钮区
        self._button_frame = tk.Frame(self, bg=COLORS["bg"])
        self._button_frame.pack(fill="x", padx=40, pady=(10, 30))

        self._prev_btn = tk.Button(
            self._button_frame,
            text=t("wizard.btn.prev"),
            font=FONTS["body"],
            bg=COLORS["surface"],
            fg=COLORS["fg"],
            relief="flat",
            padx=20,
            pady=6,
            command=self._prev_step,
        )

        self._next_btn = tk.Button(
            self._button_frame,
            text=t("wizard.btn.next"),
            font=FONTS["body"],
            bg=COLORS["accent"],
            fg=COLORS["bg"],
            relief="flat",
            padx=20,
            pady=6,
            command=self._next_step,
        )

        self._build_step_welcome()
        self._build_step_ngrok()
        self._build_step_apikey()
        self._build_step_confirm()
        self._show_step(0)

    # ---- 欢迎页 ----
    def _build_step_welcome(self) -> None:
        frame = tk.Frame(self._content, bg=COLORS["bg"])
        tk.Label(
            frame,
            text=t("wizard.welcome.title"),
            font=FONTS["heading"],
            bg=COLORS["bg"],
            fg=COLORS["fg"],
        ).pack(anchor="w", pady=(0, 16))

        info_text = t("wizard.welcome.body")
        tk.Label(
            frame,
            text=info_text,
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
            justify="left",
            wraplength=460,
        ).pack(anchor="w")
        self._steps.append(frame)

    # ---- ngrok authtoken 页 ----
    def _build_step_ngrok(self) -> None:
        frame = tk.Frame(self._content, bg=COLORS["bg"])
        tk.Label(
            frame,
            text=t("wizard.ngrok.title"),
            font=FONTS["heading"],
            bg=COLORS["bg"],
            fg=COLORS["fg"],
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(
            frame,
            text=t("wizard.ngrok.desc"),
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        link_frame = tk.Frame(frame, bg=COLORS["bg"])
        link_frame.pack(anchor="w", pady=(0, 12))
        tk.Label(
            link_frame,
            text=t("wizard.ngrok.get_token"),
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
        ).pack(side="left")
        link = tk.Label(
            link_frame,
            text="https://dashboard.ngrok.com/get-started/your-authtoken",
            font=FONTS["small"],
            bg=COLORS["bg"],
            fg=COLORS["accent_dim"],
            cursor="hand2",
        )
        link.pack(side="left")

        tk.Label(
            frame,
            text=t("wizard.ngrok.token_label"),
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["fg"],
        ).pack(anchor="w", pady=(8, 2))

        entry = tk.Entry(
            frame,
            textvariable=self._token_var,
            font=FONTS["body"],
            bg=COLORS["surface"],
            fg=COLORS["fg"],
            insertbackground=COLORS["fg"],
            relief="flat",
            width=50,
            show="*",
        )
        entry.pack(fill="x", ipady=4)
        entry.bind("<Control-a>", lambda e: entry.select_range(0, "end"))

        self._steps.append(frame)

    # ---- API Key 页 ----
    def _build_step_apikey(self) -> None:
        frame = tk.Frame(self._content, bg=COLORS["bg"])
        tk.Label(
            frame,
            text=t("wizard.apikey.title"),
            font=FONTS["heading"],
            bg=COLORS["bg"],
            fg=COLORS["fg"],
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(
            frame,
            text=t("wizard.apikey.desc"),
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        link_frame = tk.Frame(frame, bg=COLORS["bg"])
        link_frame.pack(anchor="w", pady=(0, 12))
        tk.Label(
            link_frame,
            text=t("wizard.apikey.get_key"),
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
        ).pack(side="left")
        link = tk.Label(
            link_frame,
            text="https://platform.deepseek.com/api_keys",
            font=FONTS["small"],
            bg=COLORS["bg"],
            fg=COLORS["accent_dim"],
            cursor="hand2",
        )
        link.pack(side="left")

        tk.Label(
            frame,
            text=t("wizard.apikey.label"),
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["fg"],
        ).pack(anchor="w", pady=(8, 2))

        entry = tk.Entry(
            frame,
            textvariable=self._api_key_var,
            font=FONTS["body"],
            bg=COLORS["surface"],
            fg=COLORS["fg"],
            insertbackground=COLORS["fg"],
            relief="flat",
            width=50,
            show="*",
        )
        entry.pack(fill="x", ipady=4)
        entry.bind("<Control-a>", lambda e: entry.select_range(0, "end"))

        self._steps.append(frame)

    # ---- 确认页 ----
    def _build_step_confirm(self) -> None:
        frame = tk.Frame(self._content, bg=COLORS["bg"])
        tk.Label(
            frame,
            text=t("wizard.confirm.title"),
            font=FONTS["heading"],
            bg=COLORS["bg"],
            fg=COLORS["fg"],
        ).pack(anchor="w", pady=(0, 16))

        self._confirm_text = tk.Text(
            frame,
            font=FONTS["mono"],
            bg=COLORS["surface"],
            fg=COLORS["fg"],
            relief="flat",
            height=8,
            width=55,
            padx=10,
            pady=10,
            state="disabled",
        )
        self._confirm_text.pack(fill="x")

        self._steps.append(frame)

    # ---- 步骤切换 ----
    def _show_step(self, index: int) -> None:
        for i, step in enumerate(self._steps):
            step.pack_forget()
        self._steps[index].pack(fill="both", expand=True)

        # 更新步骤指示器
        for widget in self._step_indicator.winfo_children():
            widget.destroy()
        dots = []
        for i in range(len(self._steps)):
            dot = tk.Label(
                self._step_indicator,
                text="●",
                font=FONTS["small"],
                bg=COLORS["bg"],
                fg=COLORS["accent"] if i <= index else COLORS["surface_bright"],
            )
            dot.pack(side="left", padx=3)
            dots.append(dot)

        # 更新按钮
        self._prev_btn.pack_forget()
        self._next_btn.pack_forget()

        if index > 0:
            self._prev_btn.pack(side="left")
        if index < len(self._steps) - 1:
            self._next_btn.config(text=t("wizard.btn.next"), command=self._next_step)
            self._next_btn.pack(side="right")
        else:
            self._next_btn.config(text=t("wizard.btn.finish"), command=self._finish)
            self._next_btn.pack(side="right")

        self._current_step = index

    def _next_step(self) -> None:
        if self._current_step < len(self._steps) - 1:
            # 在确认页更新摘要
            if self._current_step == 2:
                self._update_confirm_text()
            self._show_step(self._current_step + 1)

    def _prev_step(self) -> None:
        if self._current_step > 0:
            self._show_step(self._current_step - 1)

    def _update_confirm_text(self) -> None:
        token = self._token_var.get().strip()
        api_key = self._api_key_var.get().strip()
        lines = [
            t(
                "wizard.confirm.ngrok",
                value="****" + token[-4:] if len(token) > 4 else t("wizard.confirm.not_set"),
            ),
            t("wizard.confirm.use_ngrok"),
            t(
                "wizard.confirm.api_key",
                value="****" + api_key[-4:]
                if len(api_key) > 4
                else t("wizard.confirm.skip_api_key"),
            ),
        ]
        self._confirm_text.configure(state="normal")
        self._confirm_text.delete("1.0", "end")
        self._confirm_text.insert("1.0", "\n".join(lines))
        self._confirm_text.configure(state="disabled")

    def _finish(self) -> None:
        """完成引导，调用回调。"""
        token = self._token_var.get().strip()
        api_key = self._api_key_var.get().strip()

        if not token:
            messagebox.showwarning(
                t("wizard.warn.missing_token.title"),
                t("wizard.warn.missing_token.body"),
            )
            self._show_step(1)
            return

        self._on_complete(ngrok_token=token, api_key=api_key if api_key else None)

    def _on_language_selected(self, _event: Any = None) -> None:
        selected = self._language_var.get()
        if selected == get_locale():
            return
        set_locale(selected)
        if self._on_language_change is not None:
            self._on_language_change()


# ---------------------------------------------------------------------------
# 日志面板
# ---------------------------------------------------------------------------


class LogPanel(tk.Frame):
    """滚动日志面板，支持彩色日志级别。"""

    MAX_LINES = 500

    def __init__(self, master: tk.Widget, **kwargs: Any) -> None:
        super().__init__(master, bg=COLORS["bg"], **kwargs)
        self._build()

    def _build(self) -> None:
        # 标题栏
        header = tk.Frame(self, bg=COLORS["surface"])
        header.pack(fill="x")
        tk.Label(
            header,
            text=t("log.title"),
            font=FONTS["heading"],
            bg=COLORS["surface"],
            fg=COLORS["fg"],
        ).pack(side="left", pady=4)

        btn_frame = tk.Frame(header, bg=COLORS["surface"])
        btn_frame.pack(side="right", padx=4, pady=2)
        self._auto_scroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            btn_frame,
            text=t("log.auto_scroll"),
            variable=self._auto_scroll_var,
            font=FONTS["small"],
            bg=COLORS["surface"],
            fg=COLORS["text_dim"],
            selectcolor=COLORS["surface"],
            activebackground=COLORS["surface"],
            activeforeground=COLORS["fg"],
        ).pack(side="left")
        tk.Button(
            btn_frame,
            text=t("log.clear"),
            font=FONTS["small"],
            bg=COLORS["surface_bright"],
            fg=COLORS["fg"],
            relief="flat",
            padx=8,
            pady=1,
            command=self.clear,
        ).pack(side="left", padx=(4, 0))

        # 文本区域
        self._text = tk.Text(
            self,
            font=FONTS["mono"],
            bg=COLORS["bg"],
            fg=COLORS["fg"],
            relief="flat",
            padx=6,
            pady=4,
            wrap="word",
            state="disabled",
        )
        self._text.pack(fill="both", expand=True)

        # 颜色标签配置
        self._text.tag_configure("INFO", foreground=COLORS["green"])
        self._text.tag_configure("WARNING", foreground=COLORS["yellow"])
        self._text.tag_configure("ERROR", foreground=COLORS["red"])
        self._text.tag_configure("DEBUG", foreground=COLORS["text_dim"])

        self._text.tag_configure("bold", font=FONTS["mono"])

        # 滚动条
        scrollbar = tk.Scrollbar(self._text, command=self._text.yview)
        self._text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

    def append(self, level: str, message: str) -> None:
        """追加一条日志。"""
        self._text.configure(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self._text.insert("end", line, level.upper())
        # 限制行数
        line_count = int(self._text.index("end-1c").split(".")[0])
        if line_count > self.MAX_LINES:
            self._text.delete("1.0", f"{line_count - self.MAX_LINES}.0")
        self._text.configure(state="disabled")
        if self._auto_scroll_var.get():
            self._text.see("end")

    def clear(self) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")


# ---------------------------------------------------------------------------
# 主控制面板
# ---------------------------------------------------------------------------


class Dashboard(tk.Frame):
    """主控制面板：启动/停止、URL 显示、日志、设置。"""

    _SETTING_KEYS = (
        ("dashboard.settings.model", "model"),
        ("dashboard.settings.base_url", "base_url"),
        ("dashboard.settings.port", "port"),
        ("dashboard.settings.thinking", "thinking"),
        ("dashboard.settings.reasoning_effort", "reasoning_effort"),
        ("dashboard.settings.update_channel", "update_channel"),
        ("dashboard.settings.service_mode", "service_mode"),
    )

    def __init__(
        self,
        master: tk.Widget,
        config: ProxyConfig,
        controller: ProxyController,
        log_queue: queue.Queue[logging.LogRecord],
        status_queue: queue.Queue[dict[str, Any]],
        on_language_change: Any = None,
        on_data_cleared: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, bg=COLORS["bg"], **kwargs)
        self._config = config
        self._controller = controller
        self._log_queue = log_queue
        self._status_queue = status_queue
        self._on_language_change = on_language_change
        self._on_data_cleared = on_data_cleared
        self._public_url: str | None = None
        self._local_url: str | None = None
        self._setting_labels: list[tk.Label] = []

        self._build()

    def _build(self) -> None:
        # --- 顶部：标题 + 状态 ---
        header = tk.Frame(self, bg=COLORS["bg"])
        header.pack(fill="x", padx=30, pady=(24, 0))

        tk.Label(
            header,
            text="DeepSeek Cursor Proxy",
            font=FONTS["title"],
            bg=COLORS["bg"],
            fg=COLORS["accent"],
        ).pack(side="left")

        self._status_frame = tk.Frame(header, bg=COLORS["bg"])
        self._status_frame.pack(side="right")

        self._status_dot = tk.Label(
            self._status_frame,
            text="●",
            font=FONTS["heading"],
            bg=COLORS["bg"],
            fg=COLORS["red"],
        )
        self._status_dot.pack(side="left", padx=(0, 4))

        self._status_label = tk.Label(
            self._status_frame,
            text=t("dashboard.status.stopped"),
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
        )
        self._status_label.pack(side="left")

        # --- 中部：URL 区域 ---
        url_frame = tk.Frame(self, bg=COLORS["surface"], padx=20, pady=16)
        url_frame.pack(fill="x", padx=30, pady=(16, 0))

        tk.Label(
            url_frame,
            text=t("dashboard.url.label"),
            font=FONTS["body"],
            bg=COLORS["surface"],
            fg=COLORS["text_dim"],
        ).pack(anchor="w")

        url_row = tk.Frame(url_frame, bg=COLORS["surface"])
        url_row.pack(fill="x", pady=(4, 0))

        self._url_var = tk.StringVar(value=t("dashboard.url.wait"))
        self._url_entry = tk.Entry(
            url_row,
            textvariable=self._url_var,
            font=FONTS["url"],
            bg=COLORS["bg"],
            fg=COLORS["accent_dim"],
            relief="flat",
            readonlybackground=COLORS["bg"],
            state="readonly",
        )
        self._url_entry.pack(side="left", fill="x", expand=True, ipady=3)

        self._copy_btn = tk.Button(
            url_row,
            text=t("dashboard.btn.copy"),
            font=FONTS["body"],
            bg=COLORS["accent"],
            fg=COLORS["bg"],
            relief="flat",
            padx=12,
            pady=2,
            command=self._copy_url,
        )
        self._copy_btn.pack(side="left", padx=(8, 0))

        self._url_hint_label = tk.Label(
            url_frame,
            text=t("dashboard.url.hint"),
            font=FONTS["small"],
            bg=COLORS["surface"],
            fg=COLORS["text_dim"],
        ).pack(anchor="w", pady=(6, 0))

        # --- 控制按钮 ---
        ctrl_frame = tk.Frame(self, bg=COLORS["bg"])
        ctrl_frame.pack(fill="x", padx=30, pady=(16, 0))

        self._toggle_btn = tk.Button(
            ctrl_frame,
            text=t("dashboard.btn.start"),
            font=FONTS["heading"],
            bg=COLORS["green"],
            fg=COLORS["bg"],
            relief="flat",
            padx=36,
            pady=8,
            command=self._toggle_proxy,
        )
        self._toggle_btn.pack()

        # --- 设置面板（可折叠）---
        self._settings_visible = False
        self._settings_frame = tk.Frame(self, bg=COLORS["bg"])
        self._build_settings()

        self._settings_toggle = tk.Button(
            self,
            text=t("dashboard.settings.show"),
            font=FONTS["small"],
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
            relief="flat",
            command=self._toggle_settings,
        )
        self._settings_toggle.pack(pady=(6, 0))

        # --- 底部：日志面板 ---
        self._log_panel = LogPanel(self)
        self._log_panel.pack(fill="both", expand=True, padx=30, pady=12)

    def _build_settings(self) -> None:
        sf = tk.Frame(self._settings_frame, bg=COLORS["surface"], padx=16, pady=12)
        sf.pack(fill="x", padx=30)

        labels = list(self._SETTING_KEYS)

        self._setting_vars: dict[str, tk.StringVar] = {}
        for i, (label_key, key) in enumerate(labels):
            row = tk.Frame(sf, bg=COLORS["surface"])
            row.pack(fill="x", pady=3)
            label = tk.Label(
                row,
                text=f"{t(label_key)}:",
                font=FONTS["body"],
                bg=COLORS["surface"],
                fg=COLORS["text_dim"],
                width=12,
                anchor="e",
            )
            label.pack(side="left", padx=(0, 8))
            self._setting_labels.append(label)

            default = getattr(self._config, key, "")
            var = tk.StringVar(value=str(default))
            self._setting_vars[key] = var

            entry = tk.Entry(
                row,
                textvariable=var,
                font=FONTS["body"],
                bg=COLORS["bg"],
                fg=COLORS["fg"],
                insertbackground=COLORS["fg"],
                relief="flat",
                width=30,
            )
            entry.pack(side="left", ipady=2)

        lang_row = tk.Frame(sf, bg=COLORS["surface"])
        lang_row.pack(fill="x", pady=(10, 3))
        self._language_label = tk.Label(
            lang_row,
            text=f"{t('language.label')}:",
            font=FONTS["body"],
            bg=COLORS["surface"],
            fg=COLORS["text_dim"],
            width=12,
            anchor="e",
        )
        self._language_label.pack(side="left", padx=(0, 8))
        self._language_var = tk.StringVar(value=get_locale())
        self._language_combo = ttk.Combobox(
            lang_row,
            textvariable=self._language_var,
            values=list(SUPPORTED_LOCALES),
            state="readonly",
            width=28,
        )
        self._language_combo.pack(side="left")
        self._language_combo.bind("<<ComboboxSelected>>", self._on_language_selected)

        clear_row = tk.Frame(sf, bg=COLORS["surface"])
        clear_row.pack(fill="x", pady=(14, 0))
        self._clear_data_btn = tk.Button(
            clear_row,
            text=t("dashboard.clear_data.btn"),
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["red"],
            relief="flat",
            padx=12,
            pady=4,
            command=self._clear_data,
        )
        self._clear_data_btn.pack(anchor="w")

        tool_row = tk.Frame(sf, bg=COLORS["surface"])
        tool_row.pack(fill="x", pady=(10, 0))
        self._check_update_btn = tk.Button(
            tool_row,
            text=t("dashboard.update.check"),
            font=FONTS["small"],
            bg=COLORS["bg"],
            fg=COLORS["accent"],
            relief="flat",
            padx=10,
            pady=3,
            command=self._check_updates,
        )
        self._check_update_btn.pack(side="left")

        self._service_btn = tk.Button(
            tool_row,
            text=t("dashboard.service.install"),
            font=FONTS["small"],
            bg=COLORS["bg"],
            fg=COLORS["accent_dim"],
            relief="flat",
            padx=10,
            pady=3,
            command=self._install_service_helper,
        )
        self._service_btn.pack(side="left", padx=(8, 0))

    def _clear_data(self) -> None:
        if not messagebox.askyesno(
            t("dashboard.clear_data.confirm.title"),
            t("dashboard.clear_data.confirm.body"),
        ):
            return

        if self._controller.is_running:
            self._controller.stop()
            self._set_state("stopping", t("dashboard.status.stopping"))
            self._clear_data_btn.configure(state="disabled")
            self.after(200, self._clear_data_after_stop)
            return

        self._perform_clear_data()

    def _clear_data_after_stop(self) -> None:
        if self._controller.is_running:
            self.after(200, self._clear_data_after_stop)
            return
        self._clear_data_btn.configure(state="normal")
        self._set_state("stopped", t("dashboard.status.stopped"))
        self._url_var.set(t("dashboard.url.wait"))
        self._perform_clear_data()

    def _perform_clear_data(self) -> None:
        try:
            result = clear_local_data(config=self._config)
        except Exception as exc:
            messagebox.showerror(
                t("dashboard.clear_data.error.title"),
                t("dashboard.clear_data.error.body", error=exc),
            )
            return

        if not result.ok:
            messagebox.showerror(
                t("dashboard.clear_data.error.title"),
                t("dashboard.clear_data.error.body", error="\n".join(result.errors)),
            )
            return

        token_status = (
            t("dashboard.clear_data.success.token_removed")
            if result.authtoken_cleared
            else t("dashboard.clear_data.success.token_not_found")
        )
        cache_status = (
            t("dashboard.clear_data.success.cache_rows", count=result.cache_rows_cleared)
            if result.cache_rows_cleared
            else t("dashboard.clear_data.success.cache_empty")
        )
        messagebox.showinfo(
            t("dashboard.clear_data.success.title"),
            t(
                "dashboard.clear_data.success.body",
                token=token_status,
                cache=cache_status,
            ),
        )
        LOG.info(
            "Cleared local data: authtoken=%s cache_rows=%s",
            result.authtoken_cleared,
            result.cache_rows_cleared,
        )
        if self._on_data_cleared is not None:
            self._on_data_cleared()

    def _on_language_selected(self, _event: Any = None) -> None:
        selected = self._language_var.get()
        if selected == get_locale():
            return
        set_locale(selected)
        if self._on_language_change is not None:
            self._on_language_change()

    def _check_updates(self) -> None:
        release = fetch_latest_release(self._config)
        if release is None:
            messagebox.showwarning(
                t("dashboard.update.title"),
                t("dashboard.update.failed"),
            )
            return
        if has_update(__version__, release.tag_name):
            open_release = messagebox.askyesno(
                t("dashboard.update.title"),
                t(
                    "dashboard.update.available",
                    current=__version__,
                    latest=release.tag_name,
                ),
            )
            if open_release:
                webbrowser.open(release.html_url)
            return
        messagebox.showinfo(
            t("dashboard.update.title"),
            t("dashboard.update.latest", current=__version__),
        )

    def _install_service_helper(self) -> None:
        if sys.platform == "linux":
            messagebox.showinfo(
                t("dashboard.service.title"),
                t("dashboard.service.linux_hint"),
            )
            return
        if sys.platform == "win32":
            startup_dir = (
                Path.home()
                / "AppData"
                / "Roaming"
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Startup"
            )
            startup_dir.mkdir(parents=True, exist_ok=True)
            bat_path = startup_dir / "DeepSeekCursorProxy-startup.bat"
            bat_path.write_text(
                "@echo off\r\n"
                "start \"\" \"%LOCALAPPDATA%\\Programs\\DeepSeekCursorProxy\\DeepSeekCursorProxy.exe\"\r\n",
                encoding="utf-8",
            )
            messagebox.showinfo(
                t("dashboard.service.title"),
                t("dashboard.service.windows_done", path=str(bat_path)),
            )
            return
        messagebox.showinfo(
            t("dashboard.service.title"),
            t("dashboard.service.unsupported"),
        )

    def _toggle_settings(self) -> None:
        self._settings_visible = not self._settings_visible
        if self._settings_visible:
            self._settings_frame.pack(fill="x", padx=0, pady=(6, 0), before=self._settings_toggle)
            self._settings_toggle.configure(text=t("dashboard.settings.hide"))
        else:
            self._settings_frame.pack_forget()
            self._settings_toggle.configure(text=t("dashboard.settings.show"))

    def _toggle_proxy(self) -> None:
        if self._controller.is_running:
            self._controller.stop()
            self._set_state("stopping", t("dashboard.status.stopping"))
            self._toggle_btn.configure(state="disabled")
            # 轮询等待停止
            self.after(200, self._check_stopped)
        else:
            self._controller.start(self._config)
            self._set_state("starting", t("dashboard.status.starting"))
            self._toggle_btn.configure(state="disabled", text=t("dashboard.btn.starting"))
            self._url_var.set(t("dashboard.url.wait_ngrok"))
            # 开始轮询状态
            self._poll_status()
            self._poll_logs()

    def _check_stopped(self) -> None:
        if self._controller.is_running:
            self.after(200, self._check_stopped)
            return
        self._set_state("stopped", t("dashboard.status.stopped"))
        self._toggle_btn.configure(
            state="normal", text=t("dashboard.btn.start"), bg=COLORS["green"]
        )
        self._url_var.set(t("dashboard.url.wait"))

    def _set_state(
        self, state: str, message: str, public_url: str | None = None, local_url: str | None = None
    ) -> None:
        colors = {
            "running": COLORS["green"],
            "starting": COLORS["yellow"],
            "stopping": COLORS["yellow"],
            "error": COLORS["red"],
            "stopped": COLORS["red"],
        }
        color = colors.get(state, COLORS["text_dim"])
        self._status_dot.configure(fg=color)
        self._status_label.configure(text=message)

        if state == "running":
            self._toggle_btn.configure(
                state="normal", text=t("dashboard.btn.stop"), bg=COLORS["red"]
            )
            if public_url:
                self._public_url = public_url
                base_url = public_url.rstrip("/") + "/v1"
                self._url_var.set(base_url)
            elif local_url:
                self._local_url = local_url
                self._url_var.set(local_url)
        elif state == "error":
            self._toggle_btn.configure(
                state="normal", text=t("dashboard.btn.restart"), bg=COLORS["accent"]
            )
            if local_url:
                self._url_var.set(local_url)

    def _copy_url(self) -> None:
        url = self._url_var.get()
        wait_values = {t("dashboard.url.wait"), t("dashboard.url.wait_ngrok")}
        if url and url not in wait_values:
            self.clipboard_clear()
            self.clipboard_append(url)
            self._copy_btn.configure(text=t("dashboard.btn.copied"))
            self.after(2000, lambda: self._copy_btn.configure(text=t("dashboard.btn.copy")))

    def _poll_status(self) -> None:
        try:
            while True:
                status = self._status_queue.get_nowait()
                self._set_state(**status)
        except queue.Empty:
            pass
        if self._controller.is_running:
            self.after(300, self._poll_status)

    def _poll_logs(self) -> None:
        try:
            while True:
                record = self._log_queue.get_nowait()
                message = record.getMessage()
                self._log_panel.append(record.levelname, message)
        except queue.Empty:
            pass
        if self._controller.is_running:
            self.after(150, self._poll_logs)


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------


class DeepSeekProxyGUI:
    """应用主窗口。"""

    def __init__(self, cli_config: dict[str, Any] | None = None) -> None:
        self._root = tk.Tk()
        self._root.title(t("app.title"))
        self._root.geometry("700x620")
        self._root.minsize(580, 480)
        apply_theme(self._root)

        self._log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
        self._status_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._controller = ProxyController(self._status_queue, self._log_queue)

        # 配置 GUI 日志处理器
        gui_handler = QueueLogHandler(self._log_queue)
        gui_handler.setLevel(logging.INFO)
        logging.getLogger("deepseek_cursor_proxy").addHandler(gui_handler)
        logging.getLogger("deepseek_cursor_proxy").setLevel(logging.INFO)

        # 容器
        self._container = tk.Frame(self._root, bg=COLORS["bg"])
        self._container.pack(fill="both", expand=True)

        self._dashboard: Dashboard | None = None
        self._wizard: SetupWizard | None = None

        # 检查是否已配置
        config_path = default_config_path()
        if config_path.exists() and has_authtoken_configured():
            self._show_dashboard()
        else:
            self._show_wizard()

        # 窗口关闭处理
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _show_wizard(self) -> None:
        if self._dashboard:
            self._dashboard.pack_forget()
        self._wizard = SetupWizard(
            self._container,
            on_complete=self._on_setup_complete,
            on_language_change=self._reload_interface,
        )
        self._wizard.pack(fill="both", expand=True)

    def _on_setup_complete(self, ngrok_token: str, api_key: str | None) -> None:
        """引导完成后的处理。"""
        try:
            # 配置 ngrok authtoken
            configure_authtoken(ngrok_token)
            LOG.info(t("proxy.log.authtoken_ok"))

            # 创建默认配置文件
            config_path = default_config_path()
            if not config_path.exists():
                populate_default_config_file(config_path)

            # TODO: 如果用户提供了 api_key，可以写入配置文件或环境变量

            self._show_dashboard()
        except Exception as exc:
            error_text = str(exc)
            if is_endpoint_already_online_error(error_text):
                body = t("setup.error.endpoint_in_use", error=error_text)
            else:
                body = t("setup.error.body", error=error_text)
            messagebox.showerror(t("setup.error.title"), body)
            LOG.error(t("proxy.log.setup_failed", error=exc))

    def _show_dashboard(self) -> None:
        if self._wizard:
            self._wizard.pack_forget()
        try:
            config = ProxyConfig.from_file()
        except Exception as exc:
            messagebox.showerror(
                t("config.error.title"),
                t("config.error.body", error=exc),
            )
            return
        self._dashboard = Dashboard(
            self._container,
            config=config,
            controller=self._controller,
            log_queue=self._log_queue,
            status_queue=self._status_queue,
            on_language_change=self._reload_interface,
            on_data_cleared=self._on_data_cleared,
        )
        self._dashboard.pack(fill="both", expand=True)

    def _on_data_cleared(self) -> None:
        if self._controller.is_running:
            self._controller.stop()
        if self._dashboard is not None:
            self._dashboard.pack_forget()
            self._dashboard.destroy()
            self._dashboard = None
        self._show_wizard()
        if self._wizard is not None:
            self._wizard._token_var.set("")
            self._wizard._api_key_var.set("")
            self._wizard._show_step(1)

    def _reload_interface(self) -> None:
        if self._controller.is_running:
            return

        wizard_state: dict[str, Any] | None = None
        if self._wizard is not None:
            wizard_state = {
                "step": self._wizard._current_step,
                "token": self._wizard._token_var.get(),
                "api_key": self._wizard._api_key_var.get(),
            }

        self._root.title(t("app.title"))
        if self._dashboard is not None:
            self._dashboard.pack_forget()
            self._dashboard.destroy()
            self._dashboard = None
        if self._wizard is not None:
            self._wizard.pack_forget()
            self._wizard.destroy()
            self._wizard = None

        config_path = default_config_path()
        if config_path.exists() and has_authtoken_configured():
            self._show_dashboard()
        else:
            self._show_wizard()
            if wizard_state is not None and self._wizard is not None:
                self._wizard._token_var.set(wizard_state["token"])
                self._wizard._api_key_var.set(wizard_state["api_key"])
                self._wizard._show_step(wizard_state["step"])

    def _on_close(self) -> None:
        if self._controller.is_running:
            self._controller.stop()
        self._root.destroy()

    def run(self) -> None:
        self._root.mainloop()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _log_legacy_token_cleanup() -> None:
    result = migrate_and_cleanup_legacy_tokens()
    if result.migrated_token and result.migrated_from is not None:
        LOG.info(
            t("proxy.log.legacy_token_migrated", path=result.migrated_from)
        )
    for path in result.cleared_paths:
        LOG.info(t("proxy.log.legacy_token_cleared", path=path))


def run_gui(cli_config: dict[str, Any] | None = None) -> None:
    """启动 GUI 应用。"""
    init_locale()
    _log_legacy_token_cleanup()
    app = DeepSeekProxyGUI(cli_config=cli_config)
    app.run()
