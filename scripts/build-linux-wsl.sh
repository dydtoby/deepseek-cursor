#!/bin/sh
set -e

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ"

echo "=== Building Linux portable package ==="
echo "Project: $PROJ"
uname -a

if command -v apk >/dev/null 2>&1; then
  apk add --no-cache python3 py3-pip py3-setuptools python3-tkinter tk tcl
elif command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-pip python3-tk python3-venv
fi

python3 -m pip install --upgrade pip
python3 -m pip install pyinstaller PyYAML pillow

python3 build_installer.py
chmod +x scripts/build-linux-deb.sh
scripts/build-linux-deb.sh || echo "WARNING: deb 包构建失败，已跳过"

ls -lh dist/*.zip 2>/dev/null || true
ls -lh dist/*.deb 2>/dev/null || true
