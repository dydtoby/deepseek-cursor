#!/usr/bin/env bash
set -euo pipefail

APP_NAME="DeepSeek Cursor Proxy"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(uname -s)" == "Darwin" ]]; then
  INSTALL_DIR="${HOME}/Applications/${APP_NAME}"
else
  INSTALL_DIR="${HOME}/.local/share/${APP_NAME}"
  BIN_DIR="${HOME}/.local/bin"
fi

echo "=== ${APP_NAME} 安装 ==="
echo "源目录: ${SCRIPT_DIR}"
echo "目标目录: ${INSTALL_DIR}"
echo

mkdir -p "${INSTALL_DIR}"
rsync -a --delete "${SCRIPT_DIR}/" "${INSTALL_DIR}/"

if [[ "$(uname -s)" != "Darwin" ]]; then
  mkdir -p "${BIN_DIR}"
  ln -sf "${INSTALL_DIR}/DeepSeekCursorProxy" "${BIN_DIR}/deepseek-cursor-proxy-gui"
  echo "已创建命令链接: ${BIN_DIR}/deepseek-cursor-proxy-gui"
fi

echo
echo "安装完成。运行:"
if [[ "$(uname -s)" == "Darwin" ]]; then
  echo "  open \"${INSTALL_DIR}/DeepSeekCursorProxy\""
else
  echo "  \"${INSTALL_DIR}/DeepSeekCursorProxy\""
  echo "  或: deepseek-cursor-proxy-gui"
fi
