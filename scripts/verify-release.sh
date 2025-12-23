#!/bin/bash
set -e

echo "🧹 Cleaning up..."
rm -rf src-tauri/target/release/bundle
rm -rf src-tauri/bin/djaly-server*

echo "📦 Building Backend (Sidecar)..."
# backend/build_sidecar.sh の内容を参考に、release.sh と同じ手順でビルド
cd backend
source .venv/bin/activate
# 必要な隠しインポートを含めてビルド
pyinstaller --clean --noconfirm --onefile --name djaly-server \
    --hidden-import="fastapi.applications" \
    --hidden-import="sqlmodel" \
    --hidden-import="platformdirs" \
    --hidden-import="pydantic_settings" \
    server.py

# バイナリの移動
mkdir -p ../src-tauri/bin
mv dist/djaly-server ../src-tauri/bin/djaly-server-aarch64-apple-darwin
cd ..

echo "🏗️  Building Tauri App (Release)..."
pnpm tauri build

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
