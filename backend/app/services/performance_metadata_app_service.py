import json
from typing import Any

from sqlmodel import Session

from api.schemas.performance_metadata import PerformanceMetadataWrite
from domain.models.performance_metadata import TrackPerformanceMetadata
from domain.models.track import Track
from infra.database.connection import db_lock
from infra.repositories.performance_metadata_repository import PerformanceMetadataRepository


class PerformanceMetadataNotFoundError(LookupError):
    pass


class PerformanceMetadataConflictError(RuntimeError):
    def __init__(self, current_revision: int):
        super().__init__(f"Performance metadata revision conflict; current revision is {current_revision}")
        self.current_revision = current_revision


class PerformanceMetadataValidationError(ValueError):
    pass


class PerformanceMetadataAppService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = PerformanceMetadataRepository(session)

    def _track(self, track_id: int) -> Track:
        track = self.session.get(Track, track_id)
        if track is None:
            raise PerformanceMetadataNotFoundError(f"Track {track_id} not found")
        return track

    @staticmethod
    def _decode(raw: str | None, fallback: Any) -> Any:
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return fallback

    def _item(self, track_id: int, row: TrackPerformanceMetadata | None) -> dict[str, Any]:
        if row is None:
            return {
                "track_id": track_id,
                "revision": 0,
                "cue_points": [],
                "loops": [],
                "beat_grid": None,
                "created_at": None,
                "updated_at": None,
            }
        return {
            "track_id": row.track_id,
            "revision": row.revision,
            "cue_points": self._decode(row.cue_points_json, []),
            "loops": self._decode(row.loops_json, []),
            "beat_grid": self._decode(row.beat_grid_json, None),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _validate_duration(track: Track, request: PerformanceMetadataWrite) -> None:
        duration_ms = float(track.duration or 0) * 1000
        if duration_ms <= 0:
            return
        for cue in request.cue_points:
            if cue.position_ms >= duration_ms:
                raise PerformanceMetadataValidationError(
                    f"cue point slot {cue.slot} must be before the track duration"
                )
        for loop in request.loops:
            if loop.end_ms > duration_ms:
                raise PerformanceMetadataValidationError(
                    f"loop {loop.id} must end within the track duration"
                )
        if request.beat_grid and request.beat_grid.first_beat_ms >= duration_ms:
            raise PerformanceMetadataValidationError(
                "beat_grid.first_beat_ms must be before the track duration"
            )

    def get(self, track_id: int) -> dict[str, Any]:
        self._track(track_id)
        return self._item(track_id, self.repository.get(track_id))

    def replace(self, track_id: int, request: PerformanceMetadataWrite) -> dict[str, Any]:
        # DuckDB does not provide row-level locking. Serialize the compare/write
        # pair (including the first read in this session) so revision checks
        # remain atomic across request sessions.
        with db_lock:
            track = self._track(track_id)
            self._validate_duration(track, request)
            row = self.repository.get(track_id)
            current_revision = row.revision if row else 0
            if request.revision != current_revision:
                raise PerformanceMetadataConflictError(current_revision)
            if row is None:
                row = TrackPerformanceMetadata(track_id=track_id)
            row.cue_points_json = json.dumps(
                [item.model_dump(mode="json") for item in request.cue_points],
                separators=(",", ":"),
            )
            row.loops_json = json.dumps(
                [item.model_dump(mode="json") for item in request.loops],
                separators=(",", ":"),
            )
            row.beat_grid_json = (
                json.dumps(request.beat_grid.model_dump(mode="json"), separators=(",", ":"))
                if request.beat_grid
                else None
            )
            row.revision = current_revision + 1
            self.repository.save(row)
            return self._item(track_id, row)
