<!-- <h1><img src="assets/logo.png" width="120" alt="deepseek-cursor-proxy logo" style="vertical-align: middle;">&nbsp;DeepSeek Cursor Proxy</h1> -->
<h1 align="center"><img src="assets/logo.png" width="150" alt="deepseek-cursor-proxy logo"><br>DeepSeek Cursor Proxy</h1>

[English](#english) · [中文](#中文)

> **原项目 / Upstream:** 本项目基于 [yxlao/deepseek-cursor-proxy](https://github.com/yxlao/deepseek-cursor-proxy) 开发，在其 CLI 代理核心之上增加了跨平台 GUI、便携版打包与多语言支持。  
> **This fork** adds a cross-platform GUI, portable packaging, and i18n on top of the upstream CLI proxy.

A compatibility proxy that connects Cursor to DeepSeek thinking models (`deepseek-v4-pro` and `deepseek-v4-flash`) by properly handling the `reasoning_content` field for DeepSeek tool-call reasoning API requests.

This proxy can also help **other applications and coding agents** beyond Cursor that run into the same missing `reasoning_content` issue with DeepSeek's thinking-mode API. Just point their API base URL at the proxy.

---

## 中文

### 功能简介

- 修复 Cursor 使用 DeepSeek 思考模式时的 `reasoning_content` 400 错误
- 自动启动 ngrok 公网 HTTPS 隧道，供 Cursor 访问本地代理
- 提供 **GUI 桌面版**（Windows / macOS / Linux，简体中文 / English）
- 支持 CLI 命令行模式（Windows / macOS / Linux）

### 语言 / Languages

GUI 支持：

| 语言 | 代码 |
|------|------|
| 简体中文 | `zh-CN`（默认，系统为中文时自动选择） |
| English | `en-US` |

切换方式：在 **高级设置 → 语言** 中选择，界面会立即刷新。语言偏好保存在：

```text
~/.deepseek-cursor-proxy/preferences.yaml
```

---

### 支持平台

| 平台 | GUI 便携版 | CLI | 说明 |
|------|------------|-----|------|
| Windows | ✅ 推荐 | ✅ | 解压 ZIP 或 `install.bat` |
| macOS (Intel/Apple Silicon) | ✅ | ✅ | 解压 ZIP 或 `pip install -e .` |
| Linux (amd64/arm64) | ✅ | ✅ | 解压 ZIP；GUI 需 `python3-tk` |

---

### Windows 安装指南（GUI 便携版，推荐）

#### 1. 下载并解压

从发布页或 `dist/` 目录获取：

```text
DeepSeekCursorProxy-v0.1.1-portable.zip
```

解压到任意目录，例如：

```text
C:\Tools\DeepSeekCursorProxy\
```

目录结构：

```text
DeepSeekCursorProxy/
├── DeepSeekCursorProxy.exe   # 主程序
├── ngrok.exe                 # 内置 ngrok
├── install.bat               # 可选：安装到本地 Programs
└── _internal/                # 运行时依赖（请勿删除）
```

#### 2. 首次运行与配置

1. 双击 `DeepSeekCursorProxy.exe`
2. 按引导向导完成配置：
   - **ngrok Authtoken**（必填）  
     免费注册：[ngrok Dashboard](https://dashboard.ngrok.com/get-started/your-authtoken)
   - **DeepSeek API Key**（可选）  
     也可稍后在 Cursor 中填写：[DeepSeek API Keys](https://platform.deepseek.com/api_keys)
3. 点击 **启动代理**
4. 复制界面上的 **Cursor Base URL**（形如 `https://xxx.ngrok-free.dev/v1`）

> **安全提示**：你的 token 不会被打包进 ZIP 安装包，只会保存在本机用户目录中（见下方「配置文件位置」）。

#### 3. 在 Cursor 中配置

在 Cursor 中添加自定义模型：

| 字段 | 填写内容 |
|------|----------|
| Model | `deepseek-v4-pro` 或 `deepseek-v4-flash` |
| API Key | 你的 DeepSeek API Key |
| Base URL | GUI 中显示的 HTTPS 地址（须包含 `/v1`） |

示例：

```text
https://example.ngrok-free.dev/v1
```

<img src="assets/cursor_config.png" width="600" alt="Cursor settings for DeepSeek through the proxy">

快捷键切换自定义 API：

- Windows/Linux：`Ctrl+Shift+0`
- macOS：`Cmd+Shift+0`

#### 4. 可选：安装到本机

运行目录中的 `install.bat`，会将程序复制到：

```text
%LOCALAPPDATA%\Programs\DeepSeekCursorProxy\
```

并在开始菜单和桌面创建快捷方式。

#### 5. 常见问题

**ngrok 隧道启动失败**

- 若本机已有其他 ngrok 在运行，请先关闭：
  - Windows：`Get-Process ngrok | Stop-Process -Force`
  - macOS/Linux：`pkill -f ngrok`
- 新版本会自动复用已有、指向 `127.0.0.1:9000` 的隧道
- 查看 GUI 日志中的 ngrok 具体错误信息

**Cursor 无法连接**

- 确认 Base URL 末尾包含 `/v1`
- 确认代理已启动且 URL 为 `https://` 开头（非 `127.0.0.1`）

**切换语言**

- 主界面 → **高级设置** → **语言** → 选择 `zh-CN` 或 `en-US`

---

### macOS / Linux 安装指南

#### 方式 A：GUI 便携版（与 Windows 类似）

1. 从 Release 下载对应平台的 ZIP，例如：  
   `DeepSeekCursorProxy-v0.1.1-portable-darwin-arm64.zip`  
   `DeepSeekCursorProxy-v0.1.1-portable-linux-amd64.zip`
2. 解压后运行 `DeepSeekCursorProxy`（macOS 可能需在「隐私与安全性」中允许）
3. Linux 需安装 tkinter：`sudo apt install python3-tk`（Debian/Ubuntu）或发行版等价包
4. 按引导配置 ngrok authtoken 并启动代理

可选安装脚本：

```bash
chmod +x install.sh start-proxy.sh
./install.sh
```

#### 方式 B：从源码安装（CLI / GUI 开发模式）

```bash
git clone https://github.com/dydtoby/deepseek-cursor.git
cd deepseek-cursor
pip install -e .

# CLI
deepseek-cursor-proxy

# GUI
deepseek-cursor-proxy-gui
```

或使用仓库中的 `scripts/start-proxy.sh`（需已安装 ngrok）。

---

### 从源码构建便携包

在 **目标操作系统** 上执行（PyInstaller 需在对应平台构建）：

```bash
git clone https://github.com/dydtoby/deepseek-cursor.git
cd deepseek-cursor
pip install -e ".[build]"
python build_installer.py
```

构建产物：

| 文件 | 说明 |
|------|------|
| `dist/DeepSeekCursorProxy-v0.1.1-portable-<os>-<arch>.zip` | 当前平台的便携版 ZIP |
| `dist/DeepSeekCursorProxy/DeepSeekCursorProxy[.exe]` | 可直接运行 |

> Windows 上若已安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)，还会生成 `.exe` 安装程序。

---

### 配置文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| 代理配置 | `~/.deepseek-cursor-proxy/config.yaml` | 端口、模型、ngrok 等 |
| 语言偏好 | `~/.deepseek-cursor-proxy/preferences.yaml` | `language: zh-CN` 或 `en-US` |
| ngrok token | 见下表 | 由 GUI 向导通过 ngrok CLI 写入 |
| 推理缓存 | `~/.deepseek-cursor-proxy/reasoning_content.sqlite3` | 自动创建 |

**ngrok 配置文件（按系统）：**

| 系统 | 路径 |
|------|------|
| Windows | `%LOCALAPPDATA%\ngrok\ngrok.yml` |
| macOS | `~/Library/Application Support/ngrok/ngrok.yml` |
| Linux | `~/.config/ngrok/ngrok.yml` |

---

## English

### What It Does

- ✅ Injects `reasoning_content` into outgoing tool-call requests since Cursor does not include the field, restoring previously cached reasoning from regular and streamed DeepSeek responses. See [DeepSeek docs](https://api-docs.deepseek.com/guides/thinking_mode#tool-calls) for more details.
- ✅ Displays DeepSeek's thinking tokens in Cursor by forwarding them into Cursor-visible collapsible Markdown `<details><summary>Thinking</summary>...</details>` blocks.
- ✅ Starts an ngrok tunnel so Cursor can reach the local proxy through a public HTTPS URL.
- ✅ Provides other compatibility fixes to make DeepSeek models run well in Cursor.
- ✅ Cross-platform GUI (Windows / macOS / Linux) with **Simplified Chinese** and **English** UI.

### Why This Exists

This repository fixes the following Cursor + DeepSeek tool-call error with thinking mode enabled:

<img src="assets/error_400.png" width="600" alt="Error 400 - reasoning_content must be passed back">

```txt
⚠️ Connection Error
Provider returned error:
{
  "error": {
    "message": "The reasoning_content in the thinking mode must be passed back to the API.",
    "type": "invalid_request_error",
    "param": null,
    "code": "invalid_request_error"
  }
}
```

### Supported Platforms

| Platform | GUI portable | CLI |
|----------|--------------|-----|
| Windows | ✅ | ✅ |
| macOS (Intel / Apple Silicon) | ✅ | ✅ |
| Linux (amd64 / arm64) | ✅ | ✅ (GUI needs `python3-tk`) |

### GUI (Portable)

1. Download the ZIP for your OS/arch from Releases, e.g.  
   `DeepSeekCursorProxy-v0.1.1-portable-darwin-arm64.zip`
2. Run `DeepSeekCursorProxy` (or `DeepSeekCursorProxy.exe` on Windows)
3. Complete the setup wizard (ngrok authtoken required)
4. Click **Start Proxy** and copy the **Cursor Base URL**
5. Paste it into Cursor's custom model Base URL (must end with `/v1`)

- Windows: optional `install.bat` → `%LOCALAPPDATA%\Programs\DeepSeekCursorProxy\`
- macOS/Linux: optional `./install.sh`

Change language in **Advanced Settings → Language** (`zh-CN` / `en-US`).

Build portable bundle on the target OS:

```bash
pip install -e ".[build]"
python build_installer.py
```

### Usage (CLI)

#### Step 1: Set Up ngrok

Cursor blocks non-public API URLs such as `localhost`, so the proxy needs a public HTTPS URL. [ngrok](https://ngrok.com/) can expose the local proxy to Cursor without opening router ports. Alternatively, you may use [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/setup/). Create an ngrok account and visit [ngrok's dashboard](https://dashboard.ngrok.com). You will find the authtoken and public URL there.

If you're using this proxy with another application that allows localhost API endpoints, you can skip this step entirely by setting `ngrok: false` in `~/.deepseek-cursor-proxy/config.yaml`, or by starting the proxy with `--no-ngrok`.

<img src="assets/ngrok_dashboard.png" width="600" alt="ngrok dashboard">

Then, install and authenticate ngrok once:

```bash
brew install ngrok
ngrok config add-authtoken <your-ngrok-token>
```

#### Step 2: Install and Start the Proxy Server

**Run with UV**

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install and start
# uv installs the program in .venv/ under the repo local folder
git clone https://github.com/yxlao/deepseek-cursor-proxy.git
cd deepseek-cursor-proxy
uv run deepseek-cursor-proxy
```

**Run with Conda**

```bash
# Install conda if you don't have it
# Follow: https://www.anaconda.com/docs/getting-started/miniconda/install/overview

# Install
conda create -n dcp python=3.10 -y
conda activate dcp
git clone https://github.com/yxlao/deepseek-cursor-proxy.git
cd deepseek-cursor-proxy
pip install -e .

# Start
deepseek-cursor-proxy
```

**Run GUI (development)**

```bash
pip install -e .
deepseek-cursor-proxy-gui
```

When ngrok is enabled, `deepseek-cursor-proxy` will print the ngrok public URL on start. If it differs from the one in Cursor, update it in Cursor's Base URL field.

If you use a **reserved ngrok endpoint or your own domain** (instead of a URL assigned by ngrok), pass it through to the ngrok agent as `--url=…`. Set `ngrok_url` in `~/.deepseek-cursor-proxy/config.yaml` or use `--ngrok-url` on the command line (see `ngrok http --help`). Example:

```yaml
ngrok: true
ngrok_url: https://your-subdomain.ngrok.dev
```

```bash
deepseek-cursor-proxy --ngrok-url https://your-subdomain.ngrok.dev
```

On the first run, `deepseek-cursor-proxy` will create:

- `~/.deepseek-cursor-proxy/config.yaml`: the configuration file
- `~/.deepseek-cursor-proxy/reasoning_content.sqlite3`: the reasoning content cache

Persistent settings live in `~/.deepseek-cursor-proxy/config.yaml`. You can also override the config with command-line flags, for example:

```bash
# Hide thinking tokens displaying in Cursor UI
deepseek-cursor-proxy --no-display-reasoning

# Show full incoming and outgoing requests
deepseek-cursor-proxy --verbose

# Run without ngrok (run on localhost directly)
deepseek-cursor-proxy --no-ngrok

# Use a fixed ngrok public URL (reserved endpoint / custom domain)
deepseek-cursor-proxy --ngrok-url https://your-subdomain.ngrok.dev

# Use a different local port
deepseek-cursor-proxy --port 9000
```

#### Step 3: Add Cursor Custom Model

In Cursor, add the DeepSeek custom model and point it at this proxy:

- Model: `deepseek-v4-pro`
- API Key: your DeepSeek API key
- Base URL: your ngrok HTTPS URL with the `/v1` API version path

The proxy respects the DeepSeek model name Cursor sends, such as `deepseek-v4-pro` or `deepseek-v4-flash`. The `model` field in `config.yaml` is used as a fallback only when a request does not include a model.

For example, if ngrok dashboard shows `https://example.ngrok-free.dev`, use:

```text
https://example.ngrok-free.dev/v1
```

Note: you can toggle the custom API on and off with:

- macOS: `Cmd+Shift+0`
- Windows/Linux: `Ctrl+Shift+0`

#### Step 4: Chat with DeepSeek in Cursor

Select `deepseek-v4-pro` in Cursor and use chat or agent mode as usual.

<img src="assets/cursor_chat.png" width="480" alt="Chatting with DeepSeek in Cursor">

### How It Works

- **Core fix:** DeepSeek [thinking-mode tool calls](https://api-docs.deepseek.com/guides/thinking_mode#tool-calls) require the complete **multi-round** `reasoning_content` chain to be sent back in later requests. Cursor omits that field, causing a 400 error. The proxy (`Cursor -> ngrok -> proxy -> DeepSeek API`) stores DeepSeek's original `reasoning_content` and patches missing blocks back into outgoing tool-call history.
- **Multi-conversation isolation:** To avoid collisions across concurrent conversations, the proxy scopes cache keys by a SHA-256 hash of the canonical conversation prefix (roles, content, and tool calls, excluding `reasoning_content`) plus the upstream model, configuration, and an API-key hash. Different threads get different scopes, so reused tool-call IDs do not collide. Byte-identical cloned histories produce identical scopes.
- **Context caching compatibility:** The proxy preserves compatibility by never injecting synthetic thread IDs, timestamps, or cache-control messages. It restores `reasoning_content` as the exact original string, so repeated prefixes remain intact for [DeepSeek context cache](https://api-docs.deepseek.com/guides/kv_cache). Cache hit rates are logged in the terminal output.
- **Additional compatibility fixes:** Beyond reasoning repair, the proxy converts legacy `functions`/`function_call` fields to `tools`/`tool_choice`, preserves required and named tool-choice semantics, normalizes `reasoning_effort` aliases, strips mirrored thinking display blocks from assistant content, flattens multi-part content arrays to plain text, and mirrors `reasoning_content` into Cursor-visible Markdown details blocks.

### Development

Run unit tests:

```bash
uv run python -m unittest discover -s tests
```

Run pre-commit hooks (code formatting and linting):

```bash
uv sync --dev
uv run pre-commit run --all-files
```

### Debugging

Run with verbose output:

```bash
deepseek-cursor-proxy --verbose
```

Run without ngrok for local curl testing:

```bash
deepseek-cursor-proxy --no-ngrok --port 9000 --verbose
```

Capture full structured request traces for debugging:

```bash
deepseek-cursor-proxy --verbose --trace-dir ./trace-dumps
```

Use another config file:

```bash
deepseek-cursor-proxy --config ./dev.config.yaml
```

Clear the local reasoning cache:

```bash
deepseek-cursor-proxy --clear-reasoning-cache
```
