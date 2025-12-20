from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel

class Preset(SQLModel, table=True):
    __tablename__ = "presets"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: Optional[str] = None
    preset_type: str = Field(default="all")
    filters_json: Optional[str] = Field(default="{}")
    prompt_id: Optional[int] = Field(default=None, foreign_key="prompts.id")
    
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
