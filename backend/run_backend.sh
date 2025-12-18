#!/bin/bash

# スクリプトのあるディレクトリに移動
cd "$(dirname "$0")"

# 仮想環境の有効化
export ENV=dev
source .venv/bin/activate

# 環境変数の設定
export OLLAMA_HOST=http://localhost:11434
export DB_PATH="$(pwd)/../db_data/djaly.duckdb"
export MUSIC_DIR="$(pwd)/../music_data"
# Suppress TensorFlow/Essentia logs
export TF_CPP_MIN_LOG_LEVEL=3

# ポート8001を使用しているプロセスがあれば終了
PID=$(lsof -ti:8001)
if [ ! -z "$PID" ]; then
  echo "Killing process on port 8001 (PID: $PID)..."
  kill -9 $PID
fi

# サーバーの起動
# --reload-exclude を追加して、解析中のDBファイルやログファイルの変更でリロードされないようにする
# Essentiaの不要な警告ログをgrepで除外 (stderrもstdoutにマージしてフィルタ)
uvicorn main:app --host 0.0.0.0 --port 8001 --reload --reload-exclude "*.duckdb" --reload-exclude "*.duckdb.wal" --reload-exclude "*.log" 2>&1 | grep --line-buffered -v "No network created"
