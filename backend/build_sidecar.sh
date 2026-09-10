#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
PYINSTALLER="$SCRIPT_DIR/.venv/bin/pyinstaller"
if [ ! -x "$PYINSTALLER" ]; then
  echo "PyInstaller is not installed in backend/.venv. Run backend/setup.sh first."
  exit 1
fi

ARCH_NAME=$(uname -m)
if [ "$ARCH_NAME" = "x86_64" ]; then
  TARGET_TRIPLE="x86_64-apple-darwin"
  EXPECTED_FILE_ARCH="x86_64"
elif [ "$ARCH_NAME" = "arm64" ]; then
  TARGET_TRIPLE="aarch64-apple-darwin"
  EXPECTED_FILE_ARCH="arm64"
else
  echo "Unsupported architecture: $ARCH_NAME"
  exit 1
fi

# Keep the checked-in spec authoritative. It owns dynamic imports, Rekordbox
# dependencies, Essentia libraries, and the packaged ffmpeg executable.
"$PYINSTALLER" --clean --noconfirm plumdeck-server.spec

# Tauriが期待するディレクトリにバイナリを移動し、アーキテクチャ名を付与
mkdir -p ../src-tauri/bin
mv dist/plumdeck-server "../src-tauri/bin/plumdeck-server-${TARGET_TRIPLE}"

ACTUAL_FILE_INFO=$(file "../src-tauri/bin/plumdeck-server-${TARGET_TRIPLE}")
if ! echo "$ACTUAL_FILE_INFO" | grep -q "$EXPECTED_FILE_ARCH"; then
  echo "Sidecar architecture mismatch. Expected: $EXPECTED_FILE_ARCH / Actual: $ACTUAL_FILE_INFO"
  exit 1
fi

echo "Backend build complete: src-tauri/bin/plumdeck-server-${TARGET_TRIPLE}"
