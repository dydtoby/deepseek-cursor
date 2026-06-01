"""DeepSeek Cursor Proxy GUI — tkinter 桌面应用。

包含：引导向导、主控制面板、实时日志、设置面板。
"""

from __future__ import annotations

import logging
import queue
import sys
from dataclasses import replace
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from .autostart import (
    is_login_autostart_enabled,
    resolve_autostart_executable,
    set_login_autostart,
    supports_login_autostart,
)
from .clear_data import clear_local_data
from .config import (
    ProxyConfig,
    default_config_path,
    populate_default_config_file,
    update_config_file,
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
    read_authtoken,
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
    "bg": "#11111b",
    "fg": "#cdd6f4",
    "card": "#1e1e2e",
    "surface": "#313244",
    "surface_bright": "#45475a",
    "input": "#181825",
    "accent": "#89b4fa",
    "accent_dim": "#74c7ec",
    "green": "#a6e3a1",
    "green_dim": "#1e3a2f",
    "yellow": "#f9e2af",
    "yellow_dim": "#3b3a2a",
    "red": "#f38ba8",
    "red_dim": "#3b2a35",
    "text_dim": "#a6adc8",
    "text_muted": "#6c7086",
    "border": "#45475a",
    "border_soft": "#313244",
}

FONTS = gui_fonts()
CONTENT_PAD_X = 28


class Card(tk.Frame):
    """带描边的卡片容器，content 用于放置子控件。"""

    def __init__(
        self,
        master: tk.Misc,
        *,
        padding: int = 16,
        margin_x: int = CONTENT_PAD_X,
        margin_y: int = 10,
        fill: str = "x",
        **kwargs: Any,
    ) -> None:
        super().__init__(master, bg=COLORS["bg"], **kwargs)
        self._shell = tk.Frame(
            self,
            bg=COLORS["card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        self._shell.pack(fill=fill, padx=margin_x, pady=margin_y)
        self.content = tk.Frame(self._shell, bg=COLORS["card"])
        self.content.pack(fill="both", expand=True, padx=padding, pady=padding)


def section_title(parent: tk.Misc, text: str, *, bg: str | None = None) -> tk.Label:
    bg = bg or COLORS["card"]
    return tk.Label(
        parent,
        text=text,
        font=FONTS["heading"],
        bg=bg,
        fg=COLORS["fg"],
    )


def section_divider(parent: tk.Misc, *, bg: str | None = None) -> None:
    bg = bg or COLORS["card"]
    tk.Frame(parent, bg=COLORS["border_soft"], height=1).pack(fill="x", pady=(14, 14))


def inset_frame(parent: tk.Misc, *, bg: str | None = None) -> tk.Frame:
    bg = bg or COLORS["input"]
    frame = tk.Frame(
        parent,
        bg=bg,
        highlightbackground=COLORS["border_soft"],
        highlightthickness=1,
    )
    return frame


def btn_primary(
    parent: tk.Misc,
    text: str,
    command: Any,
    *,
    bg: str | None = None,
    fg: str | None = None,
) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        font=FONTS["heading"],
        bg=bg or COLORS["accent"],
        fg=fg or COLORS["bg"],
        activebackground=COLORS["accent_dim"],
        activeforeground=COLORS["bg"],
        relief="flat",
        borderwidth=0,
        padx=28,
        pady=10,
        cursor="hand2",
        command=command,
    )


def btn_secondary(
    parent: tk.Misc,
    text: str,
    command: Any,
    *,
    accent: bool = False,
) -> tk.Button:
    bg = COLORS["surface_bright"] if not accent else COLORS["surface"]
    fg = COLORS["accent"] if accent else COLORS["fg"]
    return tk.Button(
        parent,
        text=text,
        font=FONTS["body"],
        bg=bg,
        fg=fg,
        activebackground=COLORS["surface"],
        activeforeground=COLORS["fg"],
        relief="flat",
        borderwidth=0,
        padx=14,
        pady=6,
        cursor="hand2",
        command=command,
    )


def btn_ghost(parent: tk.Misc, text: str, command: Any) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        font=FONTS["small"],
        bg=COLORS["bg"],
        fg=COLORS["text_dim"],
        activebackground=COLORS["surface"],
        activeforeground=COLORS["fg"],
        relief="flat",
        borderwidth=0,
        padx=8,
        pady=4,
        cursor="hand2",
        command=command,
    )


def status_badge(parent: tk.Misc) -> tuple[tk.Frame, tk.Label, tk.Label]:
    """返回 (外框, 状态点, 状态文字)。"""
    frame = tk.Frame(
        parent,
        bg=COLORS["surface"],
        highlightbackground=COLORS["border_soft"],
        highlightthickness=1,
    )
    inner = tk.Frame(frame, bg=COLORS["surface"])
    inner.pack(padx=10, pady=6)
    dot = tk.Label(inner, text="●", font=FONTS["body"], bg=COLORS["surface"], fg=COLORS["red"])
    dot.pack(side="left", padx=(0, 6))
    label = tk.Label(
        inner,
        text="",
        font=FONTS["small"],
        bg=COLORS["surface"],
        fg=COLORS["text_dim"],
    )
    label.pack(side="left")
    return frame, dot, label


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
    style.configure(
        "TEntry",
        fieldbackground=COLORS["input"],
        foreground=COLORS["fg"],
        font=FONTS["body"],
        insertcolor=COLORS["fg"],
        borderwidth=0,
    )
    style.configure(
        "TCombobox",
        fieldbackground=COLORS["input"],
        background=COLORS["surface"],
        foreground=COLORS["fg"],
        arrowcolor=COLORS["text_dim"],
        borderwidth=0,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", COLORS["input"])],
        selectbackground=[("readonly", COLORS["accent"])],
        selectforeground=[("readonly", COLORS["bg"])],
    )
    style.configure("TCheckbutton", background=COLORS["card"], foreground=COLORS["fg"], font=FONTS["body"])
    style.configure(
        "Vertical.TScrollbar",
        background=COLORS["surface_bright"],
        troughcolor=COLORS["bg"],
        borderwidth=0,
        arrowcolor=COLORS["text_muted"],
    )
    style.configure("TLabelframe", background=COLORS["bg"], foreground=COLORS["text_dim"], font=FONTS["body"])
    style.configure("TLabelframe.Label", background=COLORS["bg"], foreground=COLORS["text_dim"], font=FONTS["body"])


class ScrollableHost(tk.Frame):
    """可垂直滚动的容器，用于主窗口与向导内容区。"""

    def __init__(self, master: tk.Widget, **kwargs: Any) -> None:
        super().__init__(master, bg=COLORS["bg"], **kwargs)
        self._canvas = tk.Canvas(self, bg=COLORS["bg"], highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self._canvas.yview
        )
        self.inner = tk.Frame(self._canvas, bg=COLORS["bg"])
        self._inner_window = self._canvas.create_window(
            (0, 0), window=self.inner, anchor="nw"
        )
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel()

    def _on_inner_configure(self, _event: tk.Event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self._canvas.itemconfigure(self._inner_window, width=event.width)

    def _bind_mousewheel(self) -> None:
        def _scroll(event: tk.Event) -> None:
            if sys.platform == "darwin":
                self._canvas.yview_scroll(int(-event.delta), "units")
            else:
                self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _scroll_up(_event: tk.Event) -> None:
            self._canvas.yview_scroll(-1, "units")

        def _scroll_down(_event: tk.Event) -> None:
            self._canvas.yview_scroll(1, "units")

        def _bind(_event: tk.Event) -> None:
            if sys.platform == "linux":
                self._canvas.bind_all("<Button-4>", _scroll_up)
                self._canvas.bind_all("<Button-5>", _scroll_down)
            else:
                self._canvas.bind_all("<MouseWheel>", _scroll)

        def _unbind(_event: tk.Event) -> None:
            if sys.platform == "linux":
                self._canvas.unbind_all("<Button-4>")
                self._canvas.unbind_all("<Button-5>")
            else:
                self._canvas.unbind_all("<MouseWheel>")

        self._canvas.bind("<Enter>", _bind)
        self._canvas.bind("<Leave>", _unbind)


# ---------------------------------------------------------------------------
# 引导向导 — 首次运行配置
# ---------------------------------------------------------------------------


class SetupWizard(tk.Frame):
    """首次运行引导向导：配置 ngrok authtoken。"""

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

        self._build()

    def _build(self) -> None:
        header = tk.Frame(self, bg=COLORS["bg"])
        header.pack(fill="x", pady=(24, 4), padx=CONTENT_PAD_X)
        title_row = tk.Frame(header, bg=COLORS["bg"])
        title_row.pack(fill="x")
        tk.Label(
            title_row,
            text="DeepSeek Cursor Proxy",
            font=FONTS["title"],
            bg=COLORS["bg"],
            fg=COLORS["accent"],
        ).pack(side="left")
        tk.Label(
            title_row,
            text=f"v{__version__}",
            font=FONTS["caption"],
            bg=COLORS["surface"],
            fg=COLORS["text_dim"],
            padx=8,
            pady=2,
        ).pack(side="left", padx=(12, 0))
        tk.Label(
            header,
            text=t("wizard.subtitle"),
            font=FONTS["subtitle"],
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
        ).pack(anchor="w", pady=(6, 0))

        lang_frame = tk.Frame(header, bg=COLORS["bg"])
        lang_frame.pack(anchor="w", pady=(10, 0))
        tk.Label(
            lang_frame,
            text=f"{t('language.label')}:",
            font=FONTS["small"],
            bg=COLORS["bg"],
            fg=COLORS["text_muted"],
        ).pack(side="left", padx=(0, 8))
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

        self._step_indicator = tk.Frame(self, bg=COLORS["bg"])
        self._step_indicator.pack(fill="x", pady=(16, 8), padx=CONTENT_PAD_X)

        # 内容区（可滚动）
        self._scroll = ScrollableHost(self)
        self._scroll.pack(fill="both", expand=True, padx=20, pady=10)
        self._content = self._scroll.inner
        content_pad = tk.Frame(self._content, bg=COLORS["bg"])
        content_pad.pack(fill="both", expand=True, padx=20)
        self._content = content_pad

        # 按钮区
        self._button_frame = tk.Frame(self, bg=COLORS["bg"])
        self._button_frame.pack(fill="x", padx=40, pady=(10, 30))

        self._prev_btn = btn_secondary(
            self._button_frame,
            t("wizard.btn.prev"),
            self._prev_step,
        )

        self._next_btn = btn_primary(
            self._button_frame,
            t("wizard.btn.next"),
            self._next_step,
        )

        self._build_step_welcome()
        self._build_step_ngrok()
        self._build_step_confirm()
        self._show_step(0)

    # ---- 欢迎页 ----
    def _build_step_welcome(self) -> None:
        frame = tk.Frame(self._content, bg=COLORS["bg"])
        card = Card(frame, margin_x=0, margin_y=0, fill="both")
        card.pack(fill="both", expand=True)
        c = card.content
        section_title(c, t("wizard.welcome.title")).pack(anchor="w", pady=(0, 12))
        tk.Label(
            c,
            text=t("wizard.welcome.body"),
            font=FONTS["body"],
            bg=COLORS["card"],
            fg=COLORS["text_dim"],
            justify="left",
            wraplength=480,
        ).pack(anchor="w")
        self._steps.append(frame)

    # ---- ngrok authtoken 页 ----
    def _build_step_ngrok(self) -> None:
        frame = tk.Frame(self._content, bg=COLORS["bg"])
        card = Card(frame, margin_x=0, margin_y=0, fill="both")
        card.pack(fill="both", expand=True)
        c = card.content
        section_title(c, t("wizard.ngrok.title")).pack(anchor="w", pady=(0, 8))
        tk.Label(
            c,
            text=t("wizard.ngrok.desc"),
            font=FONTS["body"],
            bg=COLORS["card"],
            fg=COLORS["text_dim"],
            wraplength=480,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        link_frame = tk.Frame(c, bg=COLORS["card"])
        link_frame.pack(anchor="w", pady=(0, 12))
        tk.Label(
            link_frame,
            text=t("wizard.ngrok.get_token"),
            font=FONTS["small"],
            bg=COLORS["card"],
            fg=COLORS["text_muted"],
        ).pack(side="left")
        tk.Label(
            link_frame,
            text="https://dashboard.ngrok.com/get-started/your-authtoken",
            font=FONTS["small"],
            bg=COLORS["card"],
            fg=COLORS["accent_dim"],
            cursor="hand2",
        ).pack(side="left", padx=(4, 0))

        tk.Label(
            c,
            text=t("wizard.ngrok.token_label"),
            font=FONTS["small"],
            bg=COLORS["card"],
            fg=COLORS["text_dim"],
        ).pack(anchor="w", pady=(0, 4))
        entry_box = inset_frame(c)
        entry_box.pack(fill="x")
        entry = tk.Entry(
            entry_box,
            textvariable=self._token_var,
            font=FONTS["mono"],
            bg=COLORS["input"],
            fg=COLORS["fg"],
            insertbackground=COLORS["fg"],
            relief="flat",
            borderwidth=0,
        )
        entry.pack(fill="x", ipady=8, padx=10, pady=6)
        entry.bind("<Control-a>", lambda e: entry.select_range(0, "end"))

        self._steps.append(frame)

    # ---- 确认页 ----
    def _build_step_confirm(self) -> None:
        frame = tk.Frame(self._content, bg=COLORS["bg"])
        card = Card(frame, margin_x=0, margin_y=0, fill="both")
        card.pack(fill="both", expand=True)
        c = card.content
        section_title(c, t("wizard.confirm.title")).pack(anchor="w", pady=(0, 12))

        confirm_scroll = inset_frame(c)
        confirm_scroll.pack(fill="both", expand=True)
        self._confirm_text = tk.Text(
            confirm_scroll,
            font=FONTS["mono"],
            bg=COLORS["input"],
            fg=COLORS["fg"],
            relief="flat",
            height=8,
            width=55,
            padx=10,
            pady=10,
            state="disabled",
            wrap="word",
            borderwidth=0,
        )
        confirm_bar = ttk.Scrollbar(
            confirm_scroll, orient="vertical", command=self._confirm_text.yview
        )
        self._confirm_text.configure(yscrollcommand=confirm_bar.set)
        self._confirm_text.pack(side="left", fill="both", expand=True)
        confirm_bar.pack(side="right", fill="y")

        self._steps.append(frame)

    # ---- 步骤切换 ----
    def _show_step(self, index: int) -> None:
        for i, step in enumerate(self._steps):
            step.pack_forget()
        self._steps[index].pack(fill="both", expand=True)

        step_labels = [
            t("wizard.step.welcome"),
            t("wizard.step.ngrok"),
            t("wizard.step.confirm"),
        ]
        for widget in self._step_indicator.winfo_children():
            widget.destroy()
        for i, name in enumerate(step_labels):
            if i > 0:
                tk.Label(
                    self._step_indicator,
                    text="›",
                    font=FONTS["caption"],
                    bg=COLORS["bg"],
                    fg=COLORS["text_muted"],
                ).pack(side="left", padx=4)
            if i < index:
                pill_bg, pill_fg = COLORS["surface_bright"], COLORS["fg"]
            elif i == index:
                pill_bg, pill_fg = COLORS["accent"], COLORS["bg"]
            else:
                pill_bg, pill_fg = COLORS["surface"], COLORS["text_muted"]
            pill = tk.Frame(self._step_indicator, bg=pill_bg)
            pill.pack(side="left")
            tk.Label(
                pill,
                text=f" {i + 1} ",
                font=FONTS["caption"],
                bg=pill_bg,
                fg=pill_fg,
            ).pack(side="left", padx=(6, 0), pady=4)
            tk.Label(
                pill,
                text=name,
                font=FONTS["small"],
                bg=pill_bg,
                fg=pill_fg,
            ).pack(side="left", padx=(2, 8), pady=4)

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
            if self._current_step == 1:
                self._update_confirm_text()
            self._show_step(self._current_step + 1)

    def _prev_step(self) -> None:
        if self._current_step > 0:
            self._show_step(self._current_step - 1)

    def _update_confirm_text(self) -> None:
        token = self._token_var.get().strip()
        lines = [
            t(
                "wizard.confirm.ngrok",
                value=token if token else t("wizard.confirm.not_set"),
            ),
            t("wizard.confirm.use_ngrok"),
            t("wizard.confirm.cursor_api_key"),
        ]
        self._confirm_text.configure(state="normal")
        self._confirm_text.delete("1.0", "end")
        self._confirm_text.insert("1.0", "\n".join(lines))
        self._confirm_text.configure(state="disabled")

    def _finish(self) -> None:
        """完成引导，调用回调。"""
        token = self._token_var.get().strip()

        if not token:
            messagebox.showwarning(
                t("wizard.warn.missing_token.title"),
                t("wizard.warn.missing_token.body"),
            )
            self._show_step(1)
            return

        self._on_complete(ngrok_token=token)

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
        card = Card(self, margin_x=CONTENT_PAD_X, margin_y=8)
        card.pack(fill="x")
        c = card.content

        header = tk.Frame(c, bg=COLORS["card"])
        header.pack(fill="x")
        tk.Label(
            header,
            text=t("log.title"),
            font=FONTS["heading"],
            bg=COLORS["card"],
            fg=COLORS["fg"],
        ).pack(side="left")

        btn_frame = tk.Frame(header, bg=COLORS["card"])
        btn_frame.pack(side="right")
        self._auto_scroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            btn_frame,
            text=t("log.auto_scroll"),
            variable=self._auto_scroll_var,
            font=FONTS["small"],
            bg=COLORS["card"],
            fg=COLORS["text_dim"],
            selectcolor=COLORS["input"],
            activebackground=COLORS["card"],
            activeforeground=COLORS["fg"],
        ).pack(side="left", padx=(0, 8))
        btn_secondary(btn_frame, t("log.clear"), self.clear).pack(side="left")

        text_frame = inset_frame(c)
        text_frame.pack(fill="x", pady=(12, 0))

        self._text = tk.Text(
            text_frame,
            font=FONTS["mono"],
            bg=COLORS["input"],
            fg=COLORS["fg"],
            relief="flat",
            padx=8,
            pady=6,
            wrap="word",
            state="disabled",
            height=12,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(
            text_frame, orient="vertical", command=self._text.yview
        )
        self._text.configure(yscrollcommand=scrollbar.set)
        self._text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 颜色标签配置
        self._text.tag_configure("INFO", foreground=COLORS["green"])
        self._text.tag_configure("WARNING", foreground=COLORS["yellow"])
        self._text.tag_configure("ERROR", foreground=COLORS["red"])
        self._text.tag_configure("DEBUG", foreground=COLORS["text_dim"])

        self._text.tag_configure("bold", font=FONTS["mono"])

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
        self._scroll = ScrollableHost(self)
        self._scroll.pack(fill="both", expand=True)
        body = self._scroll.inner

        # --- 顶栏 ---
        header = tk.Frame(body, bg=COLORS["bg"])
        header.pack(fill="x", padx=CONTENT_PAD_X, pady=(20, 4))
        title_block = tk.Frame(header, bg=COLORS["bg"])
        title_block.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_block,
            text="DeepSeek Cursor Proxy",
            font=FONTS["title"],
            bg=COLORS["bg"],
            fg=COLORS["accent"],
        ).pack(anchor="w")
        tk.Label(
            title_block,
            text=t("dashboard.subtitle"),
            font=FONTS["subtitle"],
            bg=COLORS["bg"],
            fg=COLORS["text_dim"],
        ).pack(anchor="w", pady=(2, 0))

        meta = tk.Frame(header, bg=COLORS["bg"])
        meta.pack(side="right")
        tk.Label(
            meta,
            text=f"v{__version__}",
            font=FONTS["caption"],
            bg=COLORS["surface"],
            fg=COLORS["text_dim"],
            padx=8,
            pady=3,
        ).pack(anchor="e", pady=(0, 8))
        self._status_frame, self._status_dot, self._status_label = status_badge(meta)
        self._status_frame.pack(anchor="e")
        self._status_label.configure(text=t("dashboard.status.stopped"))

        # --- Cursor 连接地址 ---
        url_card = Card(body, margin_y=12)
        url_card.pack(fill="x")
        uc = url_card.content
        tk.Label(
            uc,
            text=t("dashboard.url.label"),
            font=FONTS["small"],
            bg=COLORS["card"],
            fg=COLORS["text_dim"],
        ).pack(anchor="w")
        url_row = tk.Frame(uc, bg=COLORS["card"])
        url_row.pack(fill="x", pady=(8, 0))
        url_inset = inset_frame(url_row)
        url_inset.pack(side="left", fill="x", expand=True)
        self._url_var = tk.StringVar(value=t("dashboard.url.wait"))
        self._url_entry = tk.Entry(
            url_inset,
            textvariable=self._url_var,
            font=FONTS["url"],
            bg=COLORS["input"],
            fg=COLORS["accent_dim"],
            relief="flat",
            readonlybackground=COLORS["input"],
            state="readonly",
            borderwidth=0,
        )
        self._url_entry.pack(fill="x", ipady=8, padx=10, pady=4)
        self._copy_btn = btn_secondary(
            url_row,
            t("dashboard.btn.copy"),
            self._copy_url,
            accent=True,
        )
        self._copy_btn.pack(side="left", padx=(10, 0))
        self._url_hint_label = tk.Label(
            uc,
            text=t("dashboard.url.hint"),
            font=FONTS["caption"],
            bg=COLORS["card"],
            fg=COLORS["text_muted"],
        )
        self._url_hint_label.pack(anchor="w", pady=(8, 0))

        # --- 主操作 ---
        ctrl_card = Card(body, margin_y=6)
        ctrl_card.pack(fill="x")
        self._toggle_btn = btn_primary(
            ctrl_card.content,
            t("dashboard.btn.start"),
            self._toggle_proxy,
            bg=COLORS["green"],
        )
        self._toggle_btn.pack(pady=4)

        # --- 设置（可折叠）---
        self._settings_visible = False
        self._settings_frame = tk.Frame(body, bg=COLORS["bg"])
        self._build_settings()
        self._settings_toggle_row = tk.Frame(body, bg=COLORS["bg"])
        self._settings_toggle_row.pack(fill="x", pady=(4, 0))
        self._settings_toggle = btn_ghost(
            self._settings_toggle_row,
            t("dashboard.settings.show"),
            self._toggle_settings,
        )
        self._settings_toggle.pack(padx=CONTENT_PAD_X, anchor="w")

        # --- 底部：日志面板 ---
        self._log_panel = LogPanel(body)
        self._log_panel.pack(fill="x", padx=30, pady=12)

    def _build_settings(self) -> None:
        settings_card = Card(self._settings_frame, margin_x=CONTENT_PAD_X, margin_y=6)
        settings_card.pack(fill="x")
        sf = settings_card.content

        section_title(sf, t("dashboard.credentials.title")).pack(anchor="w", pady=(0, 10))

        self._ngrok_token_var = tk.StringVar(value=read_authtoken() or "")
        self._deepseek_api_key_var = tk.StringVar(
            value=self._config.deepseek_api_key or ""
        )
        self._credential_labels: list[tk.Label] = []

        for label_key, var in (
            ("dashboard.credentials.ngrok", self._ngrok_token_var),
            ("dashboard.credentials.deepseek", self._deepseek_api_key_var),
        ):
            row = tk.Frame(sf, bg=COLORS["card"])
            row.pack(fill="x", pady=4)
            label = tk.Label(
                row,
                text=f"{t(label_key)}:",
                font=FONTS["small"],
                bg=COLORS["card"],
                fg=COLORS["text_dim"],
                width=14,
                anchor="e",
            )
            label.pack(side="left", padx=(0, 10))
            self._credential_labels.append(label)
            entry_box = inset_frame(row)
            entry_box.pack(side="left", fill="x", expand=True)
            entry = tk.Entry(
                entry_box,
                textvariable=var,
                font=FONTS["mono"],
                bg=COLORS["input"],
                fg=COLORS["fg"],
                insertbackground=COLORS["fg"],
                relief="flat",
                borderwidth=0,
            )
            entry.pack(fill="x", ipady=6, padx=8, pady=4)

        self._deepseek_key_hint = tk.Label(
            sf,
            text=t("dashboard.credentials.deepseek_hint"),
            font=FONTS["caption"],
            bg=COLORS["card"],
            fg=COLORS["text_muted"],
            wraplength=520,
            justify="left",
        )
        self._deepseek_key_hint.pack(anchor="w", padx=(0, 0), pady=(0, 4))

        cred_btn_row = tk.Frame(sf, bg=COLORS["card"])
        cred_btn_row.pack(fill="x", pady=(8, 4))
        self._save_credentials_btn = btn_primary(
            cred_btn_row,
            t("dashboard.credentials.save"),
            self._save_credentials,
        )
        self._save_credentials_btn.configure(font=FONTS["body"], padx=16, pady=6)
        self._save_credentials_btn.pack(anchor="w")

        section_divider(sf)

        section_title(sf, t("dashboard.settings.general")).pack(anchor="w", pady=(0, 8))

        labels = list(self._SETTING_KEYS)

        self._setting_vars: dict[str, tk.StringVar] = {}
        for i, (label_key, key) in enumerate(labels):
            row = tk.Frame(sf, bg=COLORS["card"])
            row.pack(fill="x", pady=4)
            label = tk.Label(
                row,
                text=f"{t(label_key)}:",
                font=FONTS["small"],
                bg=COLORS["card"],
                fg=COLORS["text_dim"],
                width=14,
                anchor="e",
            )
            label.pack(side="left", padx=(0, 10))
            self._setting_labels.append(label)

            default = getattr(self._config, key, "")
            var = tk.StringVar(value=str(default))
            self._setting_vars[key] = var

            entry_box = inset_frame(row)
            entry_box.pack(side="left", fill="x", expand=True)
            entry = tk.Entry(
                entry_box,
                textvariable=var,
                font=FONTS["body"],
                bg=COLORS["input"],
                fg=COLORS["fg"],
                insertbackground=COLORS["fg"],
                relief="flat",
                borderwidth=0,
            )
            entry.pack(fill="x", ipady=5, padx=8, pady=3)

        lang_row = tk.Frame(sf, bg=COLORS["card"])
        lang_row.pack(fill="x", pady=(10, 3))
        self._language_label = tk.Label(
            lang_row,
            text=f"{t('language.label')}:",
            font=FONTS["small"],
            bg=COLORS["card"],
            fg=COLORS["text_dim"],
            width=14,
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

        self._autostart_cb = None
        if supports_login_autostart():
            autostart_row = tk.Frame(sf, bg=COLORS["card"])
            autostart_row.pack(fill="x", pady=(10, 3))
            self._autostart_label = tk.Label(
                autostart_row,
                text=f"{t('dashboard.autostart.label')}:",
                font=FONTS["small"],
                bg=COLORS["card"],
                fg=COLORS["text_dim"],
                width=14,
                anchor="e",
            )
            self._autostart_label.pack(side="left", padx=(0, 10))
            self._autostart_var = tk.BooleanVar(
                value=is_login_autostart_enabled(),
            )
            self._autostart_cb = tk.Checkbutton(
                autostart_row,
                text=t("dashboard.autostart.checkbox"),
                variable=self._autostart_var,
                font=FONTS["body"],
                bg=COLORS["card"],
                fg=COLORS["fg"],
                activebackground=COLORS["card"],
                activeforeground=COLORS["fg"],
                selectcolor=COLORS["input"],
                relief="flat",
                command=self._on_autostart_toggled,
            )
            self._autostart_cb.pack(side="left")
            self._apply_autostart_preference()

        section_divider(sf)

        section_title(sf, t("dashboard.settings.tools")).pack(anchor="w", pady=(0, 8))

        tool_row = tk.Frame(sf, bg=COLORS["card"])
        tool_row.pack(fill="x")
        self._check_update_btn = btn_secondary(
            tool_row,
            t("dashboard.update.check"),
            self._check_updates,
            accent=True,
        )
        self._check_update_btn.pack(side="left", padx=(0, 8))

        if sys.platform == "linux":
            self._service_btn = btn_secondary(
                tool_row,
                t("dashboard.service.install"),
                self._install_service_helper,
            )
            self._service_btn.pack(side="left")

        clear_row = tk.Frame(sf, bg=COLORS["card"])
        clear_row.pack(fill="x", pady=(14, 0))
        self._clear_data_btn = tk.Button(
            clear_row,
            text=t("dashboard.clear_data.btn"),
            font=FONTS["body"],
            bg=COLORS["red_dim"],
            fg=COLORS["red"],
            activebackground=COLORS["surface"],
            activeforeground=COLORS["red"],
            relief="flat",
            borderwidth=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self._clear_data,
        )
        self._clear_data_btn.pack(anchor="w")

    def _refresh_credentials(self) -> None:
        if hasattr(self, "_ngrok_token_var"):
            self._ngrok_token_var.set(read_authtoken() or "")
        if hasattr(self, "_deepseek_api_key_var"):
            try:
                refreshed = ProxyConfig.from_file()
                self._deepseek_api_key_var.set(refreshed.deepseek_api_key or "")
                self._config = refreshed
            except Exception:
                self._deepseek_api_key_var.set("")

    def _save_credentials(self) -> None:
        ngrok_token = self._ngrok_token_var.get().strip()
        api_key = self._deepseek_api_key_var.get().strip()
        ngrok_skipped = False

        if ngrok_token:
            try:
                configure_authtoken(ngrok_token)
            except Exception as exc:
                messagebox.showerror(
                    t("dashboard.credentials.title"),
                    t("dashboard.credentials.ngrok_save_failed", error=exc),
                )
                return
        else:
            ngrok_skipped = True

        try:
            update_config_file(
                {"deepseek_api_key": api_key},
            )
            self._config = replace(
                self._config,
                deepseek_api_key=api_key or None,
            )
        except Exception as exc:
            messagebox.showerror(
                t("dashboard.credentials.title"),
                t("dashboard.credentials.config_save_failed", error=exc),
            )
            return

        if ngrok_skipped:
            messagebox.showinfo(
                t("dashboard.credentials.title"),
                f"{t('dashboard.credentials.saved')}\n{t('dashboard.credentials.ngrok_empty')}",
            )
        else:
            messagebox.showinfo(
                t("dashboard.credentials.title"),
                t("dashboard.credentials.saved"),
            )

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
        self._refresh_credentials()
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

    def _apply_autostart_preference(self) -> None:
        """若配置要求自启但注册表未设置，则在启动 GUI 时同步一次。"""
        if not supports_login_autostart() or self._autostart_cb is None:
            return
        if self._config.auto_start and not is_login_autostart_enabled():
            if resolve_autostart_executable() is None:
                return
            ok, _ = set_login_autostart(True)
            if ok:
                self._autostart_var.set(True)

    def _on_autostart_toggled(self) -> None:
        if not supports_login_autostart() or self._autostart_cb is None:
            return

        enabled = bool(self._autostart_var.get())
        if enabled and resolve_autostart_executable() is None:
            self._autostart_var.set(False)
            messagebox.showinfo(
                t("dashboard.autostart.title"),
                t("dashboard.autostart.need_install"),
            )
            return

        ok, detail = set_login_autostart(enabled)
        if not ok:
            self._autostart_var.set(not enabled)
            if detail == "executable_not_found":
                messagebox.showerror(
                    t("dashboard.autostart.title"),
                    t("dashboard.autostart.need_install"),
                )
            else:
                messagebox.showerror(
                    t("dashboard.autostart.title"),
                    t("dashboard.autostart.failed", error=detail),
                )
            return

        try:
            update_config_file({"auto_start": enabled})
            self._config = replace(self._config, auto_start=enabled)
        except Exception as exc:
            messagebox.showwarning(
                t("dashboard.autostart.title"),
                t("dashboard.autostart.config_save_failed", error=exc),
            )

    def _install_service_helper(self) -> None:
        if sys.platform == "linux":
            messagebox.showinfo(
                t("dashboard.service.title"),
                t("dashboard.service.linux_hint"),
            )
            return
        messagebox.showinfo(
            t("dashboard.service.title"),
            t("dashboard.service.unsupported"),
        )

    def _toggle_settings(self) -> None:
        self._settings_visible = not self._settings_visible
        if self._settings_visible:
            self._settings_frame.pack(
                fill="x",
                pady=(4, 0),
                before=self._settings_toggle_row,
            )
            self._settings_toggle.configure(text=f"▾ {t('dashboard.settings.hide')}")
        else:
            self._settings_frame.pack_forget()
            self._settings_toggle.configure(text=f"▸ {t('dashboard.settings.show')}")

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
        state_styles = {
            "running": (COLORS["green"], COLORS["green_dim"]),
            "starting": (COLORS["yellow"], COLORS["yellow_dim"]),
            "stopping": (COLORS["yellow"], COLORS["yellow_dim"]),
            "error": (COLORS["red"], COLORS["red_dim"]),
            "stopped": (COLORS["red"], COLORS["red_dim"]),
        }
        dot_color, badge_bg = state_styles.get(
            state, (COLORS["text_muted"], COLORS["surface"])
        )
        self._status_dot.configure(fg=dot_color, bg=badge_bg)
        self._status_label.configure(text=message, fg=COLORS["text_dim"], bg=badge_bg)
        self._status_frame.configure(bg=badge_bg)
        for child in self._status_frame.winfo_children():
            child.configure(bg=badge_bg)
            for sub in child.winfo_children():
                if isinstance(sub, tk.Label):
                    sub.configure(bg=badge_bg)

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
        self._root.geometry("760x720")
        self._root.minsize(620, 520)
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

    def _on_setup_complete(self, ngrok_token: str) -> None:
        """引导完成后的处理。"""
        try:
            # 配置 ngrok authtoken
            configure_authtoken(ngrok_token)
            LOG.info(t("proxy.log.authtoken_ok"))

            # 创建默认配置文件
            config_path = default_config_path()
            if not config_path.exists():
                populate_default_config_file(config_path)

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
            self._wizard._show_step(1)

    def _reload_interface(self) -> None:
        if self._controller.is_running:
            return

        wizard_state: dict[str, Any] | None = None
        if self._wizard is not None:
            wizard_state = {
                "step": self._wizard._current_step,
                "token": self._wizard._token_var.get(),
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
