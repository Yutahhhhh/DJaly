from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlmodel import Field, SQLModel
from sqlalchemy import JSON, Column
import json

# Import moved models
from domain.models.track import Track, TrackAnalysis, TrackEmbedding
from domain.models.setlist import Setlist, SetlistTrack
from domain.models.setting import Setting
from domain.models.prompt import Prompt
from domain.models.preset import Preset
from domain.models.lyrics import Lyrics

