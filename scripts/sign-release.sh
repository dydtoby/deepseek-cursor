#!/usr/bin/env bash
set -euo pipefail

DIST_DIR="${1:-dist}"

if ! command -v sha256sum >/dev/null 2>&1; then
  echo "sha256sum not found"
  exit 1
fi

pushd "$DIST_DIR" >/dev/null
sha256sum *.zip *.deb 2>/dev/null > SHA256SUMS.txt || sha256sum *.zip > SHA256SUMS.txt

if command -v gpg >/dev/null 2>&1; then
  gpg --armor --detach-sign --output SHA256SUMS.txt.asc SHA256SUMS.txt
  echo "Generated SHA256SUMS.txt and SHA256SUMS.txt.asc"
else
  echo "Generated SHA256SUMS.txt (gpg not installed, skipped signature)"
fi
popd >/dev/null
