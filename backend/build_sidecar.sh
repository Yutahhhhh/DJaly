#!/bin/bash

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

# クリーンアップ
rm -rf build dist

# PyInstallerの実行
# --onefile: 1つのファイルにまとめる
# --name: バイナリ名
# --add-data: 静的ファイルやモデルがあれば追加 (例: "models/*.pb:models")
# hidden-import: 自動検出されないライブラリを指定
pyinstaller --clean --noconfirm --onefile --name djaly-server \
    --hidden-import="uvicorn.logging" \
    --hidden-import="uvicorn.loops" \
    --hidden-import="uvicorn.loops.auto" \
    --hidden-import="uvicorn.protocols" \
    --hidden-import="uvicorn.protocols.http" \
    --hidden-import="uvicorn.protocols.http.auto" \
    --hidden-import="uvicorn.lifespan" \
    --hidden-import="uvicorn.lifespan.on" \
    --hidden-import="sqlmodel" \
    --hidden-import="platformdirs" \
    --hidden-import="pydantic_settings" \
    --hidden-import="sklearn.utils._typedefs" \
    --hidden-import="sklearn.neighbors._partition_nodes" \
    --hidden-import="scipy.special.cython_special" \
    --add-data="models/msd-musicnn-1.pb:models" \
    server.py

# Tauriが期待するディレクトリにバイナリを移動し、アーキテクチャ名を付与
mkdir -p ../src-tauri/bin
mv dist/djaly-server "../src-tauri/bin/djaly-server-${TARGET_TRIPLE}"

ACTUAL_FILE_INFO=$(file "../src-tauri/bin/djaly-server-${TARGET_TRIPLE}")
if ! echo "$ACTUAL_FILE_INFO" | grep -q "$EXPECTED_FILE_ARCH"; then
  echo "Sidecar architecture mismatch. Expected: $EXPECTED_FILE_ARCH / Actual: $ACTUAL_FILE_INFO"
  exit 1
fi

echo "Backend build complete: src-tauri/bin/djaly-server-${TARGET_TRIPLE}"
