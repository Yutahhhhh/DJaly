"""Assist-mode endpoints.

Every route here is read-only with respect to both libraries: nothing is written
to the Djaly database and the rekordbox collection is only ever opened
read-only.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from api.schemas.assist import AssistRecommendRequest, DeckResolveRequest
from app.services.assist_app_service import AssistAppService
from infra.database.connection import get_session

router = APIRouter(prefix="/api/assist", tags=["assist"])


@router.get("/library-status")
def library_status(session: Session = Depends(get_session)):
    """Whether the local rekordbox collection can be read right now."""
    return AssistAppService(session).library_status()


@router.post("/decks/resolve")
def resolve_decks(payload: DeckResolveRequest, session: Session = Depends(get_session)):
    """Identify which library track each observed deck is actually holding."""
    return AssistAppService(session).resolve_decks(
        [deck.model_dump() for deck in payload.decks],
        payload.open_audio_paths,
    )


@router.post("/recommendations")
def recommendations(payload: AssistRecommendRequest, session: Session = Depends(get_session)):
    try:
        return AssistAppService(session).recommend(
            source_track_id=payload.source_track_id,
            intent=payload.intent,
            energy_direction=payload.energy_direction,
            genre_scope=payload.genre_scope,
            limit=payload.limit,
            exclude_track_ids=payload.exclude_track_ids,
            genres=payload.genres,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
