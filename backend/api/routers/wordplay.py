import math
from typing import Any, Dict, Literal, Optional, Union
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator
from sqlmodel import Session

from app.services.wordplay_app_service import (
    WordplayAppService,
    WordplayConflictError,
    WordplayNotFoundError,
    WordplayValidationError,
)
from infra.database.connection import get_session


router = APIRouter()


class WordplayPairCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_track_id: StrictInt
    to_track_id: StrictInt
    keyword: str = Field(min_length=1)
    source_phrase: str = Field(min_length=1)
    target_phrase: str = Field(min_length=1)
    source_section_position: Literal["unknown", "start", "middle", "end"] = "unknown"
    target_section_position: Literal["unknown", "start", "middle", "end"] = "unknown"
    source_cue_mode: Literal["section_end", "cue_drumming", "cue_drumming_intro"] = "section_end"
    from_timestamp: Optional[Union[StrictInt, StrictFloat]] = Field(default=None, ge=0)
    source_cue_end_timestamp: Optional[Union[StrictInt, StrictFloat]] = Field(default=None, ge=0)
    to_timestamp: Optional[Union[StrictInt, StrictFloat]] = Field(default=None, ge=0)
    target_intro_timestamp: Optional[Union[StrictInt, StrictFloat]] = Field(default=None, ge=0)
    target_landing_timestamp: Optional[Union[StrictInt, StrictFloat]] = Field(default=None, ge=0)
    transition_notes: str = ""
    source_url: str = ""
    evidence_type: Literal["hypothesis", "edit_listing", "performance"] = "hypothesis"
    verification_status: Literal["unverified", "tested"] = "unverified"

    @field_validator("keyword", "source_phrase", "target_phrase")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator(
        "from_timestamp", "source_cue_end_timestamp", "to_timestamp",
        "target_intro_timestamp", "target_landing_timestamp",
    )
    @classmethod
    def finite_timestamp(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not math.isfinite(value):
            raise ValueError("must be finite")
        return value

    @field_validator("source_url")
    @classmethod
    def http_url_or_empty(cls, value: str) -> str:
        if not value.strip():
            return ""
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be empty or an http/https URL")
        return value


class WordplayPairUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_track_id: Optional[StrictInt] = None
    to_track_id: Optional[StrictInt] = None
    keyword: Optional[str] = Field(default=None, min_length=1)
    source_phrase: Optional[str] = Field(default=None, min_length=1)
    target_phrase: Optional[str] = Field(default=None, min_length=1)
    source_section_position: Optional[Literal["unknown", "start", "middle", "end"]] = None
    target_section_position: Optional[Literal["unknown", "start", "middle", "end"]] = None
    source_cue_mode: Optional[Literal["section_end", "cue_drumming", "cue_drumming_intro"]] = None
    from_timestamp: Optional[Union[StrictInt, StrictFloat]] = Field(default=None, ge=0)
    source_cue_end_timestamp: Optional[Union[StrictInt, StrictFloat]] = Field(default=None, ge=0)
    to_timestamp: Optional[Union[StrictInt, StrictFloat]] = Field(default=None, ge=0)
    target_intro_timestamp: Optional[Union[StrictInt, StrictFloat]] = Field(default=None, ge=0)
    target_landing_timestamp: Optional[Union[StrictInt, StrictFloat]] = Field(default=None, ge=0)
    transition_notes: Optional[str] = None
    source_url: Optional[str] = None
    evidence_type: Optional[Literal["hypothesis", "edit_listing", "performance"]] = None
    verification_status: Optional[Literal["unverified", "tested"]] = None

    @field_validator("keyword", "source_phrase", "target_phrase")
    @classmethod
    def nonblank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator(
        "from_timestamp", "source_cue_end_timestamp", "to_timestamp",
        "target_intro_timestamp", "target_landing_timestamp",
    )
    @classmethod
    def finite_timestamp(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not math.isfinite(value):
            raise ValueError("must be finite")
        return value

    @field_validator("source_url")
    @classmethod
    def http_url_or_empty(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return value
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be empty or an http/https URL")
        return value


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, WordplayNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, WordplayConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, WordplayValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.get("/api/wordplay-pairs")
def list_wordplay_pairs(
    status: Optional[Literal["pending", "approved"]] = None,
    from_track_id: Optional[int] = None,
    query: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    return WordplayAppService(session).list_pairs(
        status=status,
        from_track_id=from_track_id,
        query=query,
        limit=limit,
        offset=offset,
    )


@router.post("/api/wordplay-pairs")
def propose_wordplay_pair(
    request: WordplayPairCreate,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    try:
        # Preserve which landing alias the caller actually supplied so the
        # service can synchronize it without mistaking model defaults for input.
        return WordplayAppService(session).propose_pair(
            **request.model_dump(exclude_unset=True)
        )
    except Exception as exc:
        _raise_service_error(exc)


@router.post("/api/wordplay-pairs/{pair_id}/approve")
def approve_wordplay_pair(pair_id: int, session: Session = Depends(get_session)) -> Dict[str, Any]:
    try:
        result = WordplayAppService(session).approve_pair(pair_id)
    except Exception as exc:
        _raise_service_error(exc)
    if result is None:
        raise HTTPException(status_code=404, detail="Wordplay pair not found")
    return result


@router.patch("/api/wordplay-pairs/{pair_id}")
def update_wordplay_pair(
    pair_id: int,
    request: WordplayPairUpdate,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    changes = request.model_dump(exclude_unset=True)
    try:
        result = WordplayAppService(session).update_pair(pair_id, changes)
    except Exception as exc:
        _raise_service_error(exc)
    if result is None:
        raise HTTPException(status_code=404, detail="Wordplay pair not found")
    return result


@router.delete("/api/wordplay-pairs/{pair_id}")
def reject_wordplay_pair(pair_id: int, session: Session = Depends(get_session)) -> Dict[str, bool]:
    if not WordplayAppService(session).delete_pair(pair_id):
        raise HTTPException(status_code=404, detail="Wordplay pair not found")
    return {"ok": True}
