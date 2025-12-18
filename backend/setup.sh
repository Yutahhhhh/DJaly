#!/bin/bash

# スクリプトのあるディレクトリに移動
cd "$(dirname "$0")"

# 仮想環境の作成（存在しない場合）
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# 仮想環境の有効化
source .venv/bin/activate

# 依存関係のインストール
echo "Installing dependencies..."
pip install -r requirements.txt

echo "Setup complete!"
