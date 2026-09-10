#!/bin/bash
set -euo pipefail

echo "🧹 Cleaning up..."
rm -rf src-tauri/target/release/bundle
rm -rf src-tauri/bin/djaly-server*

echo "📦 Building Backend (Sidecar)..."
ARCH_NAME=$(uname -m)
if [ "$ARCH_NAME" = "x86_64" ]; then
  TARGET_TRIPLE="x86_64-apple-darwin"
  EXPECTED_FILE_ARCH="x86_64"
elif [ "$ARCH_NAME" = "arm64" ]; then
  TARGET_TRIPLE="aarch64-apple-darwin"
  EXPECTED_FILE_ARCH="arm64"
else
  echo "❌ Unsupported architecture: $ARCH_NAME"
  exit 1
fi

# Use the exact same packaging contract as release.sh and GitHub Actions.
# The spec owns FFmpeg, Essentia/MusiCNN and MCP dependency collection.
cd backend
source .venv/bin/activate
python packaging_ffmpeg.py >/dev/null
python -m PyInstaller --clean --noconfirm djaly-server.spec

mkdir -p ../src-tauri/bin
mv dist/djaly-server "../src-tauri/bin/djaly-server-${TARGET_TRIPLE}"

ACTUAL_FILE_INFO=$(file "../src-tauri/bin/djaly-server-${TARGET_TRIPLE}")
if echo "$ACTUAL_FILE_INFO" | grep -q "$EXPECTED_FILE_ARCH"; then
  echo "✅ Sidecar architecture: $EXPECTED_FILE_ARCH"
elif [ "$TARGET_TRIPLE" = "aarch64-apple-darwin" ] && echo "$ACTUAL_FILE_INFO" | grep -q "x86_64"; then
  echo "⚠️ Sidecar is x86_64. It will run from the arm64 app through Rosetta."
  echo "   Actual: $ACTUAL_FILE_INFO"
else
  echo "❌ Sidecar architecture mismatch. Expected: $EXPECTED_FILE_ARCH / Actual: $ACTUAL_FILE_INFO"
  exit 1
fi
cd ..

echo "🏗️  Building Tauri App (Release)..."
pnpm exec tauri build

echo "🚀 Launching App..."
APP_PATH="src-tauri/target/release/bundle/macos/Djaly.app"

if [ -d "$APP_PATH" ]; then
  echo "Opening $APP_PATH"
  unset DB_PATH
  REPO_ROOT="$PWD"
  cd "$HOME"
  "$REPO_ROOT/$APP_PATH/Contents/MacOS/Djaly"
else
  echo "❌ App bundle not found!"
  exit 1
fi
