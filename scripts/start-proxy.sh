#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "=== DeepSeek Cursor Proxy ==="
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] 未找到 python3，请安装 Python 3.10+"
  exit 1
fi

PROXY_CMD=""
if command -v deepseek-cursor-proxy >/dev/null 2>&1; then
  PROXY_CMD="deepseek-cursor-proxy"
elif python3 -c "import deepseek_cursor_proxy" >/dev/null 2>&1; then
  PROXY_CMD="python3 -m deepseek_cursor_proxy"
else
  echo "[ERROR] 未安装 deepseek-cursor-proxy。请运行: pip install -e ."
  exit 1
fi

if ! command -v ngrok >/dev/null 2>&1; then
  if [[ -x "./ngrok" ]]; then
    export PATH="$(pwd):${PATH}"
  else
    echo "[ERROR] 未找到 ngrok。"
    echo "安装: https://ngrok.com/download"
    echo "然后运行: ngrok config add-authtoken YOUR_TOKEN"
    exit 1
  fi
fi

CONFIG_FILE="${HOME}/.deepseek-cursor-proxy/config.yaml"
if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "正在创建默认配置..."
  python3 -c "from deepseek_cursor_proxy.config import populate_default_config_file, default_config_path; populate_default_config_file(default_config_path())"
fi

echo "配置文件: ${CONFIG_FILE}"
echo "命令: ${PROXY_CMD}"
echo
echo "将下方 HTTPS URL 填入 Cursor Base URL（末尾加 /v1）"
echo "按 Ctrl+C 停止"
echo "----------------------------------------"
echo

exec ${PROXY_CMD}
