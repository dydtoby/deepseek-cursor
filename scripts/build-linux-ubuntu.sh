#!/bin/bash
set -e
SRC=/mnt/c/Users/31907/Documents/AAA.coding_project/cursordeepseek
BUILD=/root/deepseek-cursor-build
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-tk rsync
python3 -m pip install -q --break-system-packages pip pyinstaller PyYAML pillow
rm -rf "$BUILD"
rsync -a --exclude dist --exclude build --exclude .git "$SRC/" "$BUILD/"
cd "$BUILD"
python3 build_installer.py
mkdir -p "$SRC/dist"
APP_VER="$(python3 - <<'PY'
import tomllib
from pathlib import Path
data = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
print(data['project']['version'])
PY
)"
cp -f "dist/DeepSeekCursorProxy-v${APP_VER}-portable-linux-amd64.zip" "$SRC/dist/"
ls -lh "$SRC/dist/"*.zip
