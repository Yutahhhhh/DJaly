#!/bin/bash
set -e

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

# backend/build_sidecar.sh の内容を参考に、release.sh と同じ手順でビルド
cd backend
source .venv/bin/activate
# 必要な隠しインポートを含めてビルド (release.shと同期)
pyinstaller --clean --noconfirm --onefile --name djaly-server \
    --collect-all uvicorn \
    --collect-all starlette \
    --collect-all fastapi \
    --collect-all h11 \
    --hidden-import="uvicorn" \
    --hidden-import="uvicorn.main" \
    --hidden-import="uvicorn.config" \
    --hidden-import="uvicorn.logging" \
    --hidden-import="uvicorn.loops" \
    --hidden-import="uvicorn.loops.auto" \
    --hidden-import="uvicorn.loops.asyncio" \
    --hidden-import="uvicorn.protocols" \
    --hidden-import="uvicorn.protocols.http" \
    --hidden-import="uvicorn.protocols.http.auto" \
    --hidden-import="uvicorn.protocols.http.h11_impl" \
    --hidden-import="uvicorn.protocols.http.httptools_impl" \
    --hidden-import="uvicorn.protocols.websockets" \
    --hidden-import="uvicorn.protocols.websockets.auto" \
    --hidden-import="uvicorn.protocols.websockets.wsproto_impl" \
    --hidden-import="uvicorn.protocols.websockets.websockets_impl" \
    --hidden-import="uvicorn.lifespan" \
    --hidden-import="uvicorn.lifespan.on" \
    --hidden-import="uvicorn.lifespan.off" \
    --hidden-import="uvicorn.server" \
    --hidden-import="starlette" \
    --hidden-import="starlette.routing" \
    --hidden-import="starlette.middleware" \
    --hidden-import="starlette.applications" \
    --hidden-import="fastapi" \
    --hidden-import="fastapi.applications" \
    --hidden-import="sqlmodel" \
    --hidden-import="platformdirs" \
    --hidden-import="pydantic_settings" \
    --hidden-import="sklearn.utils._typedefs" \
    --hidden-import="sklearn.neighbors._partition_nodes" \
    --hidden-import="scipy.special.cython_special" \
    --hidden-import="h11" \
    --hidden-import="h11._connection" \
    --hidden-import="h11._state" \
    --hidden-import="anyio" \
    --hidden-import="anyio._backends" \
    --hidden-import="anyio._backends._asyncio" \
    --add-data "models/msd-musicnn-1.pb:models" \
    server.py

# バイナリの移動
mkdir -p ../src-tauri/bin
mv dist/djaly-server "../src-tauri/bin/djaly-server-${TARGET_TRIPLE}"
ACTUAL_FILE_INFO=$(file "../src-tauri/bin/djaly-server-${TARGET_TRIPLE}")
if ! echo "$ACTUAL_FILE_INFO" | grep -q "$EXPECTED_FILE_ARCH"; then
  echo "❌ Sidecar architecture mismatch. Expected: $EXPECTED_FILE_ARCH / Actual: $ACTUAL_FILE_INFO"
  echo "   Check whether the Python virtualenv or PyInstaller is running under a different architecture."
  exit 1
fi
cd ..

echo "🏗️  Building Tauri App (Release)..."
pnpm exec tauri build

echo "🚀 Launching App..."
APP_PATH="src-tauri/target/release/bundle/macos/Djaly.app"

if [ -d "$APP_PATH" ]; then
    echo "Opening $APP_PATH"
    # ログを見れるようにバックグラウンドではなく直接起動したいが、
    # .appはopenコマンドで開くのが一般的。
    # コンソールログを見るには Console.app を使うか、
    # バイナリを直接叩く:
    # 開発環境のDB_PATHが設定されているとクラッシュする原因になるためunsetする
    unset DB_PATH
    # .envファイルがカレントディレクトリにあると読み込まれてしまうため、一時的にリネームするか、
    # アプリ起動時のカレントディレクトリをホームディレクトリなどに変更する
    cd $HOME
    "$OLDPWD/$APP_PATH/Contents/MacOS/Djaly"
else
    echo "❌ App bundle not found!"
    exit 1
fi
