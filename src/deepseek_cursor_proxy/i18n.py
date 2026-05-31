"""GUI 多语言支持（简体中文 / English）。"""

from __future__ import annotations

import locale
import os
from pathlib import Path
from typing import Any

import yaml

from .config import default_app_dir

PREFERENCES_FILE_NAME = "preferences.yaml"
DEFAULT_LOCALE = "zh-CN"
SUPPORTED_LOCALES = ("zh-CN", "en-US")

_LOCALE = DEFAULT_LOCALE

TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "app.title": "DeepSeek Cursor Proxy",
        "language.label": "语言",
        "language.zh-CN": "简体中文",
        "language.en-US": "English",
        "language.restart_hint": "语言已保存，界面已更新。",
        "wizard.subtitle": "首次运行 · 配置引导",
        "wizard.welcome.title": "欢迎使用 DeepSeek Cursor Proxy",
        "wizard.welcome.body": (
            "本工具将帮助你在 Cursor 中使用 DeepSeek 思考模型。\n\n"
            "配置只需两步：\n"
            "  1. 输入 ngrok authtoken（免费注册获取）\n"
            "  2. 输入 DeepSeek API Key（可选，也可在 Cursor 中配置）\n\n"
            "完成后，代理将自动启动并提供一个 HTTPS URL，\n"
            "将其填入 Cursor 的 Base URL 即可开始使用。"
        ),
        "wizard.ngrok.title": "配置 ngrok Authtoken",
        "wizard.ngrok.desc": "ngrok 用于创建公网 HTTPS 隧道，让 Cursor 可以访问本地代理。",
        "wizard.ngrok.get_token": "获取 token: ",
        "wizard.ngrok.token_label": "ngrok Authtoken",
        "wizard.apikey.title": "配置 DeepSeek API Key（可选）",
        "wizard.apikey.desc": (
            "你可以在本应用中配置 API Key，也可稍后在 Cursor 中直接配置。\n"
            "两种方式选其一即可。如果你选择跳过，请确保在 Cursor 的\n"
            "API Key 字段中填写你的 DeepSeek API Key。"
        ),
        "wizard.apikey.get_key": "获取 API Key: ",
        "wizard.apikey.label": "DeepSeek API Key（可选）",
        "wizard.confirm.title": "确认配置",
        "wizard.confirm.ngrok": "  ngrok authtoken : {value}",
        "wizard.confirm.use_ngrok": "  使用 ngrok 隧道  : 是",
        "wizard.confirm.api_key": "  DeepSeek API Key: {value}",
        "wizard.confirm.not_set": "(未填写)",
        "wizard.confirm.skip_api_key": "(跳过，在 Cursor 中配置)",
        "wizard.btn.prev": "上一步",
        "wizard.btn.next": "下一步",
        "wizard.btn.finish": "完成配置",
        "wizard.warn.missing_token.title": "缺少 authtoken",
        "wizard.warn.missing_token.body": "请输入 ngrok authtoken 以继续。",
        "log.title": "  运行日志",
        "log.auto_scroll": "自动滚动",
        "log.clear": "清空",
        "dashboard.status.stopped": "未启动",
        "dashboard.status.starting": "正在启动...",
        "dashboard.status.stopping": "正在停止...",
        "dashboard.status.running": "代理运行中",
        "dashboard.status.running_local": "代理运行中（仅本地）",
        "dashboard.url.label": "Cursor Base URL",
        "dashboard.url.wait": "等待启动...",
        "dashboard.url.wait_ngrok": "等待 ngrok 隧道...",
        "dashboard.url.hint": "提示：在 Cursor 中添加自定义模型，Base URL 填入上方地址（需包含 /v1）",
        "dashboard.btn.copy": " 复制 ",
        "dashboard.btn.copied": " 已复制 ",
        "dashboard.btn.start": "启动代理",
        "dashboard.btn.starting": "启动中...",
        "dashboard.btn.stop": "停止代理",
        "dashboard.btn.restart": "重新启动",
        "dashboard.settings.show": "▸ 高级设置",
        "dashboard.settings.hide": "▾ 高级设置",
        "dashboard.settings.model": "模型",
        "dashboard.settings.base_url": "Base URL",
        "dashboard.settings.port": "端口",
        "dashboard.settings.thinking": "思考模式",
        "dashboard.settings.reasoning_effort": "推理强度",
        "dashboard.clear_data.btn": "清除缓存与 Token",
        "dashboard.clear_data.confirm.title": "确认清除",
        "dashboard.clear_data.confirm.body": (
            "将清除以下内容：\n\n"
            "  · ngrok authtoken（需重新配置）\n"
            "  · 本地推理缓存\n\n"
            "代理配置（端口、模型等）会保留。\n"
            "若代理正在运行，将先停止。\n\n"
            "确定继续吗？"
        ),
        "dashboard.clear_data.success.title": "清除完成",
        "dashboard.clear_data.success.body": (
            "已清除：\n"
            "  · ngrok authtoken: {token}\n"
            "  · 推理缓存: {cache} 条\n\n"
            "将返回配置引导，请重新输入 ngrok authtoken。"
        ),
        "dashboard.clear_data.success.token_removed": "已删除",
        "dashboard.clear_data.success.token_not_found": "未找到",
        "dashboard.clear_data.success.cache_rows": "{count} 条",
        "dashboard.clear_data.success.cache_empty": "无缓存",
        "dashboard.clear_data.error.title": "清除失败",
        "dashboard.clear_data.error.body": "清除过程中出错：\n{error}",
        "proxy.init_cache": "正在初始化推理缓存...",
        "proxy.start_local": "正在启动本地代理服务器...",
        "proxy.start_ngrok": "正在启动 ngrok 隧道...",
        "proxy.running": "代理运行中",
        "proxy.running_local": "代理运行中（仅本地）",
        "proxy.stopped": "代理已停止",
        "proxy.start_failed": "启动失败: {error}",
        "proxy.ngrok_failed": "ngrok 隧道启动失败: {error}",
        "proxy.log.ngrok_url": "ngrok 公网 URL: {url}",
        "proxy.log.cursor_base": "Cursor Base URL: {url}",
        "proxy.log.local_running": "本地代理仍在运行: {url}",
        "proxy.log.local_url": "本地代理 URL: {url}",
        "proxy.log.default_model": "默认模型: {model}",
        "proxy.log.cursor_hint": "请将上述 URL 填入 Cursor 的 Base URL（末尾加 /v1）",
        "proxy.log.authtoken_ok": "ngrok authtoken 配置成功",
        "proxy.log.setup_failed": "配置失败: {error}",
        "setup.error.title": "配置失败",
        "setup.error.body": "配置过程出错:\n{error}",
        "config.error.title": "配置错误",
        "config.error.body": "无法加载配置文件:\n{error}",
    },
    "en-US": {
        "app.title": "DeepSeek Cursor Proxy",
        "language.label": "Language",
        "language.zh-CN": "简体中文",
        "language.en-US": "English",
        "language.restart_hint": "Language saved. The interface has been updated.",
        "wizard.subtitle": "First Run · Setup Wizard",
        "wizard.welcome.title": "Welcome to DeepSeek Cursor Proxy",
        "wizard.welcome.body": (
            "This app helps you use DeepSeek thinking models in Cursor.\n\n"
            "Setup takes two steps:\n"
            "  1. Enter your ngrok authtoken (free account)\n"
            "  2. Enter your DeepSeek API key (optional; can be set in Cursor)\n\n"
            "After setup, the proxy starts and provides an HTTPS URL.\n"
            "Paste it into Cursor's Base URL to get started."
        ),
        "wizard.ngrok.title": "Configure ngrok Authtoken",
        "wizard.ngrok.desc": "ngrok creates a public HTTPS tunnel so Cursor can reach the local proxy.",
        "wizard.ngrok.get_token": "Get token: ",
        "wizard.ngrok.token_label": "ngrok Authtoken",
        "wizard.apikey.title": "Configure DeepSeek API Key (Optional)",
        "wizard.apikey.desc": (
            "You can set the API key here or later in Cursor.\n"
            "Either option works. If you skip this step, make sure Cursor's\n"
            "API Key field contains your DeepSeek API key."
        ),
        "wizard.apikey.get_key": "Get API key: ",
        "wizard.apikey.label": "DeepSeek API Key (optional)",
        "wizard.confirm.title": "Review Settings",
        "wizard.confirm.ngrok": "  ngrok authtoken : {value}",
        "wizard.confirm.use_ngrok": "  Use ngrok tunnel : yes",
        "wizard.confirm.api_key": "  DeepSeek API Key: {value}",
        "wizard.confirm.not_set": "(not set)",
        "wizard.confirm.skip_api_key": "(skipped; configure in Cursor)",
        "wizard.btn.prev": "Back",
        "wizard.btn.next": "Next",
        "wizard.btn.finish": "Finish Setup",
        "wizard.warn.missing_token.title": "Missing authtoken",
        "wizard.warn.missing_token.body": "Enter your ngrok authtoken to continue.",
        "log.title": "  Logs",
        "log.auto_scroll": "Auto scroll",
        "log.clear": "Clear",
        "dashboard.status.stopped": "Stopped",
        "dashboard.status.starting": "Starting...",
        "dashboard.status.stopping": "Stopping...",
        "dashboard.status.running": "Running",
        "dashboard.status.running_local": "Running (local only)",
        "dashboard.url.label": "Cursor Base URL",
        "dashboard.url.wait": "Waiting to start...",
        "dashboard.url.wait_ngrok": "Waiting for ngrok tunnel...",
        "dashboard.url.hint": "Tip: add a custom model in Cursor and paste the URL above (must include /v1)",
        "dashboard.btn.copy": " Copy ",
        "dashboard.btn.copied": " Copied ",
        "dashboard.btn.start": "Start Proxy",
        "dashboard.btn.starting": "Starting...",
        "dashboard.btn.stop": "Stop Proxy",
        "dashboard.btn.restart": "Restart",
        "dashboard.settings.show": "▸ Advanced Settings",
        "dashboard.settings.hide": "▾ Advanced Settings",
        "dashboard.settings.model": "Model",
        "dashboard.settings.base_url": "Base URL",
        "dashboard.settings.port": "Port",
        "dashboard.settings.thinking": "Thinking",
        "dashboard.settings.reasoning_effort": "Reasoning effort",
        "dashboard.clear_data.btn": "Clear Cache & Token",
        "dashboard.clear_data.confirm.title": "Confirm Clear",
        "dashboard.clear_data.confirm.body": (
            "This will remove:\n\n"
            "  · ngrok authtoken (you will need to set it up again)\n"
            "  · local reasoning cache\n\n"
            "Proxy settings (port, model, etc.) will be kept.\n"
            "If the proxy is running, it will be stopped first.\n\n"
            "Continue?"
        ),
        "dashboard.clear_data.success.title": "Clear Complete",
        "dashboard.clear_data.success.body": (
            "Removed:\n"
            "  · ngrok authtoken: {token}\n"
            "  · reasoning cache: {cache}\n\n"
            "Returning to setup. Enter your ngrok authtoken again."
        ),
        "dashboard.clear_data.success.token_removed": "removed",
        "dashboard.clear_data.success.token_not_found": "not found",
        "dashboard.clear_data.success.cache_rows": "{count} row(s)",
        "dashboard.clear_data.success.cache_empty": "empty",
        "dashboard.clear_data.error.title": "Clear Failed",
        "dashboard.clear_data.error.body": "An error occurred while clearing data:\n{error}",
        "proxy.init_cache": "Initializing reasoning cache...",
        "proxy.start_local": "Starting local proxy server...",
        "proxy.start_ngrok": "Starting ngrok tunnel...",
        "proxy.running": "Proxy running",
        "proxy.running_local": "Proxy running (local only)",
        "proxy.stopped": "Proxy stopped",
        "proxy.start_failed": "Failed to start: {error}",
        "proxy.ngrok_failed": "Failed to start ngrok tunnel: {error}",
        "proxy.log.ngrok_url": "ngrok public URL: {url}",
        "proxy.log.cursor_base": "Cursor Base URL: {url}",
        "proxy.log.local_running": "Local proxy still running: {url}",
        "proxy.log.local_url": "Local proxy URL: {url}",
        "proxy.log.default_model": "Default model: {model}",
        "proxy.log.cursor_hint": "Paste the URL above into Cursor's Base URL (append /v1)",
        "proxy.log.authtoken_ok": "ngrok authtoken configured",
        "proxy.log.setup_failed": "Setup failed: {error}",
        "setup.error.title": "Setup Failed",
        "setup.error.body": "An error occurred during setup:\n{error}",
        "config.error.title": "Configuration Error",
        "config.error.body": "Unable to load configuration:\n{error}",
    },
}


def preferences_path() -> Path:
    return default_app_dir() / PREFERENCES_FILE_NAME


def detect_system_locale() -> str:
    for env_name in ("LANG", "LC_ALL", "LC_MESSAGES"):
        lang = os.environ.get(env_name, "")
        if lang.lower().startswith("zh"):
            return "zh-CN"

    try:
        value = locale.getlocale()[0]
    except (AttributeError, ValueError, TypeError):
        value = None
    if value and str(value).lower().startswith("zh"):
        return "zh-CN"
    return "en-US"


def load_saved_locale() -> str | None:
    path = preferences_path()
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    language = data.get("language")
    if isinstance(language, str) and language in SUPPORTED_LOCALES:
        return language
    return None


def save_locale(locale_code: str) -> None:
    if locale_code not in SUPPORTED_LOCALES:
        raise ValueError(f"unsupported locale: {locale_code}")
    path = preferences_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"language": locale_code}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def init_locale() -> str:
    global _LOCALE
    _LOCALE = load_saved_locale() or detect_system_locale()
    return _LOCALE


def get_locale() -> str:
    return _LOCALE


def set_locale(locale_code: str, *, persist: bool = True) -> None:
    global _LOCALE
    if locale_code not in SUPPORTED_LOCALES:
        raise ValueError(f"unsupported locale: {locale_code}")
    _LOCALE = locale_code
    if persist:
        save_locale(locale_code)


def t(key: str, **kwargs: Any) -> str:
    table = TRANSLATIONS.get(_LOCALE) or TRANSLATIONS[DEFAULT_LOCALE]
    text = table.get(key) or TRANSLATIONS[DEFAULT_LOCALE].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except KeyError:
            return text
    return text
