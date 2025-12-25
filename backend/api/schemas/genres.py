from pydantic import BaseModel
from typing import List, Optional
from enum import Enum
from .track import TrackRead

class AnalysisMode(str, Enum):
    GENRE = "genre"
    SUBGENRE = "subgenre"
    BOTH = "both"

class GenreBatchUpdateRequest(BaseModel):
    parent_track_id: int
    target_track_ids: List[int]

class GenreBatchUpdateResponse(BaseModel):
    updated_count: int
    genre: str

class GenreCleanupRequest(BaseModel):
    target_genre: str
    track_ids: List[int]
    mode: AnalysisMode = AnalysisMode.GENRE

class GenreLLMAnalyzeRequest(BaseModel):
    track_id: int
    overwrite: bool = False
    mode: AnalysisMode = AnalysisMode.BOTH

class GenreBatchLLMAnalyzeRequest(BaseModel):
    track_ids: List[int]
    mode: AnalysisMode = AnalysisMode.BOTH
    overwrite: bool = False

class GenreUpdateResult(BaseModel):
    track_id: int
    title: str
    artist: str
    old_genre: str
    new_genre: str

class GenreAnalysisResponse(BaseModel):
    genre: str
    subgenre: str = ""
    reason: str
    confidence: str

class GenreBatchAnalysisItem(GenreAnalysisResponse):
    track_id: int

class GenreBatchAnalysisResponse(BaseModel):
    results: List[GenreBatchAnalysisItem]

class TrackSuggestion(BaseModel):
    id: int
    title: str
    artist: str
    bpm: float
    filepath: str
    current_genre: Optional[str] = None

class GroupedSuggestion(BaseModel):
    parent_track: TrackRead
    suggestions: List[TrackSuggestion]

class GroupedSuggestionSummary(BaseModel):
    parent_track: TrackRead
    suggestion_count: int

class GenreCleanupGroup(BaseModel):
    primary_genre: str
    variant_genres: List[str]
    track_count: int
    suggestions: List[TrackSuggestion]

class GenreApplyRequest(BaseModel):
    track_ids: List[int]