#!/bin/bash
set -e

echo "[INFO] Starting Djaly Backend Initialization..."

# 1. 環境変数の強制設定
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

# 2. ロックファイルのクリーンアップ
if [ -d "/db_data" ]; then
    echo "[INFO] Cleaning up potential database locks in /db_data..."
    rm -f /db_data/*.wal
    rm -f /db_data/djaly.duckdb.wal
    rm -f /db_data/djaly.duckdb.lock
else
    echo "[WARNING] /db_data directory not found. Using local directory."
fi

# 3. サーバー起動 (Reloadなし)
echo "[INFO] Launching Uvicorn Server (Single Process, No Reload)..."
exec uvicorn main:app --host 0.0.0.0 --port 8001 --workers 1 --loop asyncio