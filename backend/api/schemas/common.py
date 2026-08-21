from pydantic import BaseModel
from typing import List, Optional, Any, Dict

class ListPathRequest(BaseModel):
    path: str
    hide_analyzed: bool = False

class IngestRequest(BaseModel):
    targets: List[str]
    force_update: bool = False

class SettingUpdate(BaseModel):
    key: str
    value: str

class MetadataUpdate(BaseModel):
    track_id: int
    lyrics: Optional[str] = None
    artwork_data: Optional[str] = None