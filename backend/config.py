import os
from pydantic_settings import BaseSettings
from pydantic import Field
import platformdirs

APP_NAME = "Djaly"
APP_AUTHOR = "DjalyDev"

class Settings(BaseSettings):
    # App Info
    APP_NAME: str = APP_NAME
    APP_AUTHOR: str = APP_AUTHOR
    ENV: str = "prod"

    # Paths
    # デフォルトは platformdirs を使用するが、環境変数 DB_PATH があればそれを優先する
    USER_DATA_DIR: str = Field(default_factory=lambda: platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    DB_PATH: str | None = None
    MUSIC_DIR: str = "/music_data"
    
    # Network
    DJALY_PORT: int = 8001
    FRONTEND_PORT: int = 1420
    
    # AI/ML
    OLLAMA_HOST: str = "http://localhost:11434"
    TF_CPP_MIN_LOG_LEVEL: str = "3"
    
    # Workers
    NUM_WORKERS: int | None = None

    # Logging & Cache
    DJALY_LOG_DIR: str | None = None
    NUMBA_CACHE_DIR: str | None = None
    MPLCONFIGDIR: str | None = None

    class Config:
        env_file = ".env"
        extra = "ignore"

    def model_post_init(self, __context):
        # DB_PATHが未設定ならデフォルト値を設定
        if not self.DB_PATH:
            self.DB_PATH = os.path.join(self.USER_DATA_DIR, "djaly.duckdb")
        
        # ログディレクトリ
        if not self.DJALY_LOG_DIR:
            self.DJALY_LOG_DIR = os.path.join(self.USER_DATA_DIR, "logs")
            
        # キャッシュディレクトリ
        if not self.NUMBA_CACHE_DIR:
            self.NUMBA_CACHE_DIR = os.path.join(self.USER_DATA_DIR, ".numba_cache")
        if not self.MPLCONFIGDIR:
            self.MPLCONFIGDIR = os.path.join(self.USER_DATA_DIR, ".matplotlib")

    def setup_environment(self):
        """ライブラリが使用する環境変数を設定する"""
        if self.NUMBA_CACHE_DIR:
            os.environ["NUMBA_CACHE_DIR"] = self.NUMBA_CACHE_DIR
        if self.MPLCONFIGDIR:
            os.environ["MPLCONFIGDIR"] = self.MPLCONFIGDIR
        if self.DJALY_LOG_DIR:
            os.environ["DJALY_LOG_DIR"] = self.DJALY_LOG_DIR

settings = Settings()
