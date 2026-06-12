from typing import Optional
from sqlmodel import Field, SQLModel
from datetime import datetime

class Lyrics(SQLModel, table=True):
    __tablename__ = "lyrics"
    
    track_id: int = Field(primary_key=True, foreign_key="tracks.id")
    content: str = Field(default="")
    source: str = Field(default="user") # user, ai, metadata
    language: Optional[str] = Field(default=None)
    # ワードプレイ用キーワード抽出結果のキャッシュ (content のハッシュで鮮度管理)
    keywords_json: Optional[str] = Field(default=None)
    keywords_content_hash: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
