from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlmodel import Field, SQLModel
from sqlalchemy import JSON, Column
from pydantic import ConfigDict
import json

class Track(SQLModel, table=True):
    __tablename__ = "tracks"
    """
    音楽トラックモデル
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    filepath: str = Field(index=True, unique=True, nullable=False)
    
    # メタデータ
    title: str = Field(index=True)
    artist: str = Field(index=True)
    album: Optional[str] = Field(default="", index=True)
    genre: str
    subgenre: str = Field(default="")
    year: Optional[int] = Field(default=None, index=True)
    
    # 解析データ
    bpm: float
    key: str = Field(default="")
    scale: str = Field(default="")
    duration: float
    
    # Basic Audio Features
    energy: float = Field(default=0.0)
    danceability: float = Field(default=0.0)
    loudness: float = Field(default=-60.0)
    brightness: float = Field(default=0.0)
    noisiness: float = Field(default=0.0)
    contrast: float = Field(default=0.0)
    
    # Advanced Features
    loudness_range: float = Field(default=0.0)
    spectral_flux: float = Field(default=0.0)
    spectral_rolloff: float = Field(default=0.0)
    
    is_genre_verified: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now, index=True)

    # Pydantic V2 形式の Config 設定
    # extra="allow" により、辞書化した後に外部から has_lyrics を注入してもバリデーションエラーになりません
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="allow" 
    )

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
    embedding_json: str = Field(default="[]")
    updated_at: datetime = Field(default_factory=datetime.now)