import logging
import os
from logging.handlers import RotatingFileHandler
import sys

# ログディレクトリの作成
# 環境変数 DJALY_LOG_DIR が設定されていればそれを使用 (本番環境/server.py経由)
# 設定されていなければ、このファイルからの相対パスを使用 (開発環境)
if "DJALY_LOG_DIR" in os.environ:
    LOG_DIR = os.environ["DJALY_LOG_DIR"]
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    LOG_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(LOG_DIR, exist_ok=True)

def get_logger(name: str):
    """
    ファイル出力とコンソール出力を併用するロガーを取得する
    """
    logger = logging.getLogger(name)
    
    # ハンドラが重複して追加されないようにチェック
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # フォーマット定義
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # 1. ファイルハンドラ (10MBごとにローテーション, 最大5世代)
        log_file = os.path.join(LOG_DIR, "djaly.log")
        try:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10*1024*1024,
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.INFO)
            logger.addHandler(file_handler)
        except Exception as e:
            # 権限エラーなどでファイル作成できない場合のフォールバック
            print(f"Failed to set up file logging: {e}", file=sys.stderr)
        
        # 2. コンソールハンドラ (Docker logs / ターミナル確認用)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)
        
    return logger