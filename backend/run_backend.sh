#!/bin/bash

# スクリプトのあるディレクトリに移動
cd "$(dirname "$0")"

# 仮想環境の有効化
export ENV=dev
source .venv/bin/activate

# Load .env from project root if exists
if [ -f "../.env" ]; then
  echo "Loading environment variables from ../.env"
  set -a
  source ../.env
  set +a
fi

# 環境変数の設定
export OLLAMA_HOST=${OLLAMA_HOST:-http://localhost:11434}
export DB_PATH="$(pwd)/../db_data/djaly.duckdb"
export MUSIC_DIR="$(pwd)/../music_data"

# ポート設定 (0の場合は8001に強制)
if [ -z "$DJALY_PORT" ] || [ "$DJALY_PORT" = "0" ]; then
    export DJALY_PORT=8001
fi

echo "Starting Djaly Backend on port $DJALY_PORT..."

# Suppress TensorFlow/Essentia logs
export TF_CPP_MIN_LOG_LEVEL=3

# ポートを使用しているプロセスがあれば終了
PID=$(lsof -ti:$DJALY_PORT)
if [ ! -z "$PID" ]; then
  echo "Stopping process on port $DJALY_PORT (PID: $PID)..."
  kill $PID
  # プロセスが終了するまで待機
  while kill -0 $PID 2>/dev/null; do
    sleep 0.5
  done
fi

# サーバーの起動
# --reload-exclude を追加して、解析中のDBファイルやログファイルの変更でリロードされないようにする
# Essentiaの不要な警告ログをgrepで除外 (stderrもstdoutにマージしてフィルタ)
uvicorn main:app --host 0.0.0.0 --port $DJALY_PORT --reload --reload-exclude "*.duckdb" --reload-exclude "*.duckdb.wal" --reload-exclude "*.log" 2>&1 | grep --line-buffered -v "No network created"
