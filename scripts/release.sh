#!/bin/bash
set -e # エラーが発生したら即停止

# 設定
VERSION=$1
BINARY_NAME="djaly-server"
OUTPUT_DIR="src-tauri/bin"

# アーキテクチャの自動検出
ARCH_NAME=$(uname -m)
if [ "$ARCH_NAME" = "x86_64" ]; then
  TARGET_TRIPLE="x86_64-apple-darwin"
elif [ "$ARCH_NAME" = "arm64" ]; then
  TARGET_TRIPLE="aarch64-apple-darwin"
else
  echo "❌ 未サポートのアーキテクチャ: $ARCH_NAME"
  exit 1
fi

# 引数チェック
if [ -z "$VERSION" ]; then
  echo "使用法: ./scripts/release.sh <version_tag>"
  echo "例: ./scripts/release.sh v0.1.0"
  exit 1
fi

echo "🚀 リリースプロセスを開始します: $VERSION"

# --- 1. Python Backend Build ---
echo "📦 [1/4] Pythonバックエンドをビルド中..."
cd backend

# 仮想環境の有効化
source .venv/bin/activate

# PyInstallerの実行 (Github Actionsで使用していたコマンドと同一)
# specファイルがある場合は `pyinstaller djaly.spec` に置き換えてください
pyinstaller --clean --noconfirm --onefile --name $BINARY_NAME \
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
    --hidden-import="sqlalchemy.sql.default_comparator" \
    --hidden-import="duckdb" \
    --hidden-import="duckdb_engine" \
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
    server.py

cd ..

# --- 2. Sidecar Setup ---
echo "🚚 [2/4] バイナリをTauri用に配置中..."
mkdir -p $OUTPUT_DIR
# Tauriは "-<target-triple>" というサフィックスを期待するためリネーム
mv backend/dist/$BINARY_NAME "$OUTPUT_DIR/${BINARY_NAME}-${TARGET_TRIPLE}"
chmod +x "$OUTPUT_DIR/${BINARY_NAME}-${TARGET_TRIPLE}"

# macOSの場合、Sidecarバイナリに署名を行う（Ad-hoc署名）
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "🔏 Sidecarバイナリに署名中..."
    codesign --force --sign - "$OUTPUT_DIR/${BINARY_NAME}-${TARGET_TRIPLE}"
fi

echo "✅ バックエンド配置完了: $OUTPUT_DIR/${BINARY_NAME}-${TARGET_TRIPLE}"

# --- 3. Tauri Build ---
echo "🦀 [3/4] Tauriアプリをビルド中..."

# 署名用キーの設定 (keys/djaly.key が存在する場合)
if [ -f "keys/djaly.key" ]; then
    echo "🔑 署名用キーを読み込んでいます..."
    export TAURI_SIGNING_PRIVATE_KEY=$(cat keys/djaly.key)
    export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="djaly-password"
fi

# pnpm tauri build だと package.json の "tauri": "tauri dev" が呼ばれてしまうため
# 直接 tauri CLI を呼び出す
pnpm exec tauri build

# --- 4. GitHub Release (Optional) ---
if [ "$2" == "--skip-upload" ]; then
    echo "🚫 アップロードをスキップします。"
    echo "✅ ビルド完了: src-tauri/target/release/bundle/"
    exit 0
fi

echo "☁️ [4/4] GitHub Releasesへアップロード中..."

# GitHub CLI (gh) がインストールされているか確認
if ! command -v gh &> /dev/null; then
    echo "⚠️ 'gh' コマンドが見つかりません。手動でアップロードしてください。"
    echo "成果物パス: src-tauri/target/release/bundle/dmg/*.dmg"
    exit 0
fi

# DMGファイルのパスを取得
DMG_PATH=$(find src-tauri/target/release/bundle/dmg -name "*.dmg" | head -n 1)

if [ -z "$DMG_PATH" ]; then
    echo "❌ DMGファイルが見つかりませんでした。"
    exit 1
fi

echo "アップロードファイル: $DMG_PATH"

# 既存のリリースがある場合は削除して再作成
if gh release view "$VERSION" >/dev/null 2>&1; then
    echo "⚠️ 既存のリリース $VERSION が見つかりました。削除して再作成します..."
    gh release delete "$VERSION" -y
fi

# リリース作成とアップロード
# --draft: 下書きとして作成（公開前に確認したい場合）
# --generate-notes: コミットログからリリースノートを自動生成
gh release create "$VERSION" "$DMG_PATH" --title "Djaly $VERSION" --generate-notes

echo "🎉 リリース完了！ GitHubを確認してください。"
echo ""
echo "⚠️ 注意: Apple Developer Programに登録して署名・公証を行っていない場合、"
echo "   macOSでインストール後に「壊れているため開けません」というエラーが表示されることがあります。"
echo "   その場合は、ターミナルで以下のコマンドを実行して検疫属性を削除してください:"
echo "   xattr -cr /Applications/Djaly.app"
