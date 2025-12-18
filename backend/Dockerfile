FROM python:3.11-slim

# 音声処理に必要な最小限のランタイムライブラリ
# ffmpeg: Essentiaや各種フォーマット変換に必須
# libsndfile1: オーディオ読み込みの互換性維持のため残す
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存関係のインストール
# numpyを先にインストール（Essentiaの依存関係解決をスムーズにするため）
RUN pip install --no-cache-dir numpy

# EssentiaをPyPIからインストール
# ※ docker-compose.yml で platform: linux/amd64 を指定することで、
#   公式のビルド済みWheelがダウンロードされ、ビルド時間ゼロで導入できます。
#   (Python 3.11用のWheelも提供されています)
RUN pip install --no-cache-dir essentia

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# コードのコピー
COPY . .

# 起動スクリプトの準備 (改行コードトラブル回避のため sed で LF に変換推奨)
COPY start.sh /start.sh
RUN sed -i 's/\r$//' /start.sh && chmod +x /start.sh

# 起動コマンド
CMD ["/start.sh"]