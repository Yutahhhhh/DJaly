from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel

class Prompt(SQLModel, table=True):
    __tablename__ = "prompts"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    content: str
    is_default: bool = Field(default=False)
    display_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
