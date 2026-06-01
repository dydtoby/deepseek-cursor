#!/bin/sh
set -e

SERVICE_NAME="deepseek-cursor-proxy.service"
TARGET_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$TARGET_DIR"
cp "$(dirname "$0")/$SERVICE_NAME" "$TARGET_DIR/$SERVICE_NAME"

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"

echo "Installed user service: $SERVICE_NAME"
echo "Commands:"
echo "  systemctl --user start $SERVICE_NAME"
echo "  systemctl --user status $SERVICE_NAME"
echo "  systemctl --user stop $SERVICE_NAME"
