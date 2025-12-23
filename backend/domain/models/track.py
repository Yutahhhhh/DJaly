from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlmodel import Field, SQLModel
from sqlalchemy import JSON, Column
import json

class Track(SQLModel, table=True):
    __tablename__ = "tracks"
    """
    音楽トラックモデル
    
    DuckDBの制約により、DBスキーマは backend/db.py 内の Raw SQL で管理されます。
    ここでの定義はアプリケーション層のバリデーションとORM操作のために使用されます。
    """
    # IDはDB側でSequenceによって自動採番されるため、Python側ではOptional
    id: Optional[int] = Field(default=None, primary_key=True)

    # ファイルパスは一意である必要があります
    filepath: str = Field(index=True, unique=True, nullable=False)
    
    # メタデータ (TinyTag由来)
    title: str = Field(index=True)
    artist: str = Field(index=True)
    album: str
    genre: str
    year: Optional[int] = Field(default=None, index=True)
    
    # 解析データ (Librosa由来)
    # BPMは解析前はNone
    bpm: float
    # キー (例: 'C# maj')
    key: str = Field(default="")
    scale: str = Field(default="")
    # 曲の長さ（秒）
    duration: float
    
    # --- Basic Audio Features (Scalar - 高速検索用) ---
    energy: float = Field(default=0.0)
    danceability: float = Field(default=0.0)
    loudness: float = Field(default=-60.0)
    brightness: float = Field(default=0.0)
    noisiness: float = Field(default=0.0)
    contrast: float = Field(default=0.0)
    
    # --- Essentia Advanced Features ---
    loudness_range: float = Field(default=0.0)
    spectral_flux: float = Field(default=0.0)
    spectral_rolloff: float = Field(default=0.0)
    
    # --- User Interaction ---
    is_genre_verified: bool = Field(default=False)

    created_at: datetime = Field(default_factory=datetime.now, index=True)

    class Config:
        # データベースとの整合性を保つための設定
        arbitrary_types_allowed = True

class TrackAnalysis(SQLModel, table=True):
    __tablename__ = "track_analyses"
    track_id: int = Field(primary_key=True, foreign_key="tracks.id")
    beat_positions: List[float] = Field(default=[], sa_column=Column(JSON))
    waveform_peaks: List[float] = Field(default=[], sa_column=Column(JSON))
    features_extra_json: str = Field(default="{}")

    @property
    def features_extra(self) -> Dict[str, Any]:
        try:
            return json.loads(self.features_extra_json)
        except:
            return {}

class TrackEmbedding(SQLModel, table=True):
    __tablename__ = "track_embeddings"
    track_id: int = Field(primary_key=True, foreign_key="tracks.id")
    model_name: str = Field(default="musicnn")
    # DuckDB ARRAY type storage (stored as JSON string for SQLModel compatibility)
    embedding_json: str = Field(default="[]")
    updated_at: datetime = Field(default_factory=datetime.now)
