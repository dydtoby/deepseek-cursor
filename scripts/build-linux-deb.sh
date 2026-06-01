#!/bin/sh
set -e

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$PROJ/dist"
APP_VER="$(python3 - <<'PY'
import tomllib
from pathlib import Path
data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)"

PKG_ROOT="$DIST_DIR/deb-root"
APP_DIR="$DIST_DIR/DeepSeekCursorProxy"
PKG_NAME="deepseek-cursor-proxy"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
OUT_DEB="$DIST_DIR/${PKG_NAME}_${APP_VER}_${ARCH}.deb"

rm -rf "$PKG_ROOT"
mkdir -p "$PKG_ROOT/DEBIAN" "$PKG_ROOT/usr/local/$PKG_NAME" "$PKG_ROOT/usr/local/bin"

cp -r "$APP_DIR"/* "$PKG_ROOT/usr/local/$PKG_NAME/"

cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $APP_VER
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: DeepSeek Cursor Proxy
Description: DeepSeek Cursor Proxy packaged app
EOF

cat > "$PKG_ROOT/usr/local/bin/deepseek-cursor-proxy-gui" <<'EOF'
#!/bin/sh
exec /usr/local/deepseek-cursor-proxy/DeepSeekCursorProxy "$@"
EOF
chmod +x "$PKG_ROOT/usr/local/bin/deepseek-cursor-proxy-gui"

dpkg-deb --build "$PKG_ROOT" "$OUT_DEB"
echo "Generated: $OUT_DEB"
