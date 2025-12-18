#!/bin/bash

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
    --hidden-import="sklearn.utils._typedefs" \
    --hidden-import="sklearn.neighbors._partition_nodes" \
    --hidden-import="scipy.special.cython_special" \
    server.py

# Tauriが期待するディレクトリにバイナリを移動し、アーキテクチャ名を付与
# Apple Silicon (M1/M2/M3) 用のトリプル: aarch64-apple-darwin
mkdir -p ../src-tauri/bin
mv dist/djaly-server ../src-tauri/bin/djaly-server-aarch64-apple-darwin

echo "Backend build complete: src-tauri/bin/djaly-server-aarch64-apple-darwin"