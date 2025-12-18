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

class PromptCreate(BaseModel):
    name: str
    content: str
    is_default: bool = False

class MetadataUpdate(BaseModel):
    track_id: int
    lyrics: Optional[str] = None
    artwork_data: Optional[str] = None

class PromptUpdate(BaseModel):
    name: str
    content: str
    is_default: bool

class PresetCreate(BaseModel):
    name: str
    description: Optional[str] = None
    preset_type: str = "all"
    prompt_id: Optional[int] = None

class PresetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    preset_type: Optional[str] = None
    prompt_id: Optional[int] = None