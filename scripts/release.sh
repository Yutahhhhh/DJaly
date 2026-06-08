#!/bin/bash
set -e # エラーが発生したら即停止

# 設定
# tauri.conf.json からバージョンを取得
VERSION=$(node -p "require('./src-tauri/tauri.conf.json').version")
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

if [ -z "$VERSION" ]; then
  echo "❌ バージョンを取得できませんでした。src-tauri/tauri.conf.json を確認してください。"
  exit 1
fi

echo "🚀 リリースプロセスを開始します: v$VERSION"

# --- 1. Python Backend Build ---

# --- 1. Python Backend Build ---
echo "📦 [1/4] Pythonバックエンドをビルド中..."
cd backend

# 仮想環境の有効化
source .venv/bin/activate

# PyInstallerの実行 (specファイルを使用)
pyinstaller --clean --noconfirm djaly-server.spec

cd ..

# --- 2. Sidecar Setup ---
echo "🚚 [2/4] バイナリをTauri用に配置中..."
mkdir -p $OUTPUT_DIR
# Tauriは "-<target-triple>" というサフィックスを期待するためリネーム
mv backend/dist/$BINARY_NAME "$OUTPUT_DIR/${BINARY_NAME}-${TARGET_TRIPLE}"
chmod +x "$OUTPUT_DIR/${BINARY_NAME}-${TARGET_TRIPLE}"

if [ "$TARGET_TRIPLE" = "aarch64-apple-darwin" ]; then
  EXPECTED_FILE_ARCH="arm64"
else
  EXPECTED_FILE_ARCH="x86_64"
fi

ACTUAL_FILE_INFO=$(file "$OUTPUT_DIR/${BINARY_NAME}-${TARGET_TRIPLE}")
if ! echo "$ACTUAL_FILE_INFO" | grep -q "$EXPECTED_FILE_ARCH"; then
  echo "❌ Sidecarのアーキテクチャが一致しません。期待: $EXPECTED_FILE_ARCH / 実際: $ACTUAL_FILE_INFO"
  echo "   Python仮想環境またはPyInstallerが別アーキテクチャで動作している可能性があります。"
  exit 1
fi

# macOSの場合、Sidecarバイナリに署名を行う（Ad-hoc署名）
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "🔏 Sidecarバイナリに署名中..."
    codesign --force --sign - "$OUTPUT_DIR/${BINARY_NAME}-${TARGET_TRIPLE}"
fi

# 依存関係の検証
echo "🔍 バイナリの依存関係を検証中..."
DEPS=$(otool -L "$OUTPUT_DIR/${BINARY_NAME}-${TARGET_TRIPLE}" | grep -v "/usr/lib" | grep -v "/System/" | tail -n +2)
if [ -n "$DEPS" ]; then
    echo "⚠️ 警告: システムライブラリ以外の依存関係が検出されました:"
    echo "$DEPS"
    echo "これらのライブラリが配布先のマシンにない場合、アプリが動作しない可能性があります。"
else
    echo "✅ システムライブラリのみに依存しています（問題なし）"
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

# 署名ファイルのパスを取得
SIG_PATH="${DMG_PATH}.sig"

# latest.jsonを生成
LATEST_JSON="src-tauri/target/release/bundle/dmg/latest.json"
DMG_FILENAME=$(basename "$DMG_PATH")
DOWNLOAD_URL="https://github.com/Yutahhhhh/DJaly/releases/download/v${VERSION}/${DMG_FILENAME}"
PUB_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "📝 latest.jsonを生成中..."
if [ -f "$SIG_PATH" ]; then
    SIGNATURE=$(cat "$SIG_PATH")
    cat > "$LATEST_JSON" <<EOF
{
  "version": "${VERSION}",
  "notes": "See release notes for details",
  "pub_date": "${PUB_DATE}",
  "platforms": {
    "darwin-aarch64": {
      "signature": "${SIGNATURE}",
      "url": "${DOWNLOAD_URL}"
    }
  }
}
EOF
else
    echo "⚠️ 警告: 署名ファイル (.sig) が見つかりません。署名なしでlatest.jsonを生成します。"
    cat > "$LATEST_JSON" <<EOF
{
  "version": "${VERSION}",
  "notes": "See release notes for details",
  "pub_date": "${PUB_DATE}",
  "platforms": {
    "darwin-aarch64": {
      "url": "${DOWNLOAD_URL}"
    }
  }
}
EOF
fi

echo "✅ latest.json生成完了: $LATEST_JSON"

# 既存のリリースがある場合は削除して再作成
if gh release view "v$VERSION" >/dev/null 2>&1; then
    echo "⚠️ 既存のリリース v$VERSION が見つかりました。削除して再作成します..."
    gh release delete "v$VERSION" -y
fi

# リリース作成とアップロード（DMG、署名、latest.json）
# --draft: 下書きとして作成（公開前に確認したい場合）
# --generate-notes: コミットログからリリースノートを自動生成
echo "☁️ GitHub Releaseを作成中..."
if [ -f "$SIG_PATH" ]; then
    gh release create "v$VERSION" "$DMG_PATH" "$SIG_PATH" "$LATEST_JSON" --title "Djaly v$VERSION" --generate-notes
else
    gh release create "v$VERSION" "$DMG_PATH" "$LATEST_JSON" --title "Djaly v$VERSION" --generate-notes
fi

echo "🎉 リリース完了！ GitHubを確認してください。"
echo ""
echo "⚠️ 注意: Apple Developer Programに登録して署名・公証を行っていない場合、"
echo "   macOSでインストール後に「壊れているため開けません」というエラーが表示されることがあります。"
echo "   その場合は、ターミナルで以下のコマンドを実行して検疫属性を削除してください:"
echo "   xattr -cr /Applications/Djaly.app"
