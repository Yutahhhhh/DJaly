import math
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from sqlmodel import Session, select

from domain.models.track import Track
from domain.models.wordplay import WordplayPair
from infra.database.connection import db_lock


EVIDENCE_TYPES = {"hypothesis", "edit_listing", "performance"}
VERIFICATION_STATUSES = {"unverified", "tested"}
PAIR_STATUSES = {"pending", "approved"}
SECTION_POSITIONS = {"unknown", "start", "middle", "end"}
SOURCE_CUE_MODES = {"section_end", "cue_drumming", "cue_drumming_intro"}


class WordplayValidationError(ValueError):
    pass


class WordplayNotFoundError(LookupError):
    pass


class WordplayConflictError(RuntimeError):
    pass


class WordplayAppService:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def normalize_keyword(keyword: str) -> str:
        return keyword.strip().casefold()

    @staticmethod
    def _validate_timestamp(value: Optional[float], field: str) -> None:
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise WordplayValidationError(f"{field} must be a finite, nonnegative number")

    @staticmethod
    def _validate_url(value: str) -> None:
        if not value:
            return
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise WordplayValidationError("source_url must be empty or an http/https URL")

    @staticmethod
    def _cue_in_range(timestamp: Optional[float], track: Optional[Track]) -> bool:
        if timestamp is None or track is None:
            return False
        duration = track.duration
        return (
            duration is not None
            and math.isfinite(duration)
            and duration > 0
            and 0 <= timestamp < duration
        )

    def _validate_cues(
        self,
        values: Dict[str, Any],
        from_track: Track,
        to_track: Track,
    ) -> None:
        for field, track in (
            ("from_timestamp", from_track),
            ("source_cue_end_timestamp", from_track),
            ("to_timestamp", to_track),
            ("target_intro_timestamp", to_track),
            ("target_landing_timestamp", to_track),
        ):
            timestamp = values.get(field)
            if timestamp is not None and not self._cue_in_range(timestamp, track):
                raise WordplayValidationError(
                    f"{field} must be before the selected track duration"
                )
        cue_start = values.get("from_timestamp")
        cue_end = values.get("source_cue_end_timestamp")
        if cue_start is not None and cue_end is not None and cue_start >= cue_end:
            raise WordplayValidationError(
                "source_cue_end_timestamp must be after from_timestamp"
            )
        intro = values.get("target_intro_timestamp")
        landing = values.get("target_landing_timestamp")
        if intro is not None and landing is not None and intro >= landing:
            raise WordplayValidationError(
                "target_intro_timestamp must be before target_landing_timestamp"
            )

    def _validate_tracks(self, from_track_id: int, to_track_id: int) -> tuple[Track, Track]:
        if (
            isinstance(from_track_id, bool)
            or isinstance(to_track_id, bool)
            or not isinstance(from_track_id, int)
            or not isinstance(to_track_id, int)
        ):
            raise WordplayValidationError("from_track_id and to_track_id are required integers")
        if from_track_id == to_track_id:
            raise WordplayValidationError("from_track_id and to_track_id must be distinct")
        from_track = self.session.get(Track, from_track_id)
        to_track = self.session.get(Track, to_track_id)
        missing = [
            str(track_id)
            for track_id, track in ((from_track_id, from_track), (to_track_id, to_track))
            if track is None
        ]
        if missing:
            raise WordplayNotFoundError(f"Track(s) not found: {', '.join(missing)}")
        return from_track, to_track

    def _validate_fields(self, values: Dict[str, Any]) -> None:
        keyword = values.get("keyword", "")
        if not isinstance(keyword, str) or not self.normalize_keyword(keyword):
            raise WordplayValidationError("keyword must not be blank")
        for field in ("source_phrase", "target_phrase"):
            if not isinstance(values.get(field), str) or not values[field].strip():
                raise WordplayValidationError(f"{field} must not be blank")
        if not isinstance(values.get("transition_notes", ""), str):
            raise WordplayValidationError("transition_notes must be a string")
        if not isinstance(values.get("source_url", ""), str):
            raise WordplayValidationError("source_url must be a string")
        for field in (
            "from_timestamp", "source_cue_end_timestamp", "to_timestamp",
            "target_intro_timestamp", "target_landing_timestamp",
        ):
            self._validate_timestamp(values.get(field), field)
        self._validate_url(values.get("source_url", ""))
        if values.get("evidence_type") not in EVIDENCE_TYPES:
            raise WordplayValidationError("invalid evidence_type")
        if values.get("verification_status") not in VERIFICATION_STATUSES:
            raise WordplayValidationError("invalid verification_status")
        for field in ("source_section_position", "target_section_position"):
            if values.get(field) not in SECTION_POSITIONS:
                raise WordplayValidationError(f"invalid {field}")
        if values.get("source_cue_mode") not in SOURCE_CUE_MODES:
            raise WordplayValidationError("invalid source_cue_mode")

    @staticmethod
    def _sync_target_landing_alias(values: Dict[str, Any], supplied: set[str]) -> None:
        """Keep legacy to_timestamp and the explicit landing cue interchangeable."""
        if "to_timestamp" in supplied and "target_landing_timestamp" in supplied:
            if values.get("to_timestamp") != values.get("target_landing_timestamp"):
                raise WordplayValidationError(
                    "to_timestamp and target_landing_timestamp must match"
                )
        elif "to_timestamp" in supplied:
            values["target_landing_timestamp"] = values.get("to_timestamp")
        elif "target_landing_timestamp" in supplied:
            values["to_timestamp"] = values.get("target_landing_timestamp")
        elif values.get("target_landing_timestamp") is None:
            values["target_landing_timestamp"] = values.get("to_timestamp")

    @staticmethod
    def _track_dict(track: Track) -> Dict[str, Any]:
        return track.model_dump(mode="json")

    @staticmethod
    def _style_fit(from_track: Optional[Track], to_track: Optional[Track]) -> bool:
        """Whether the target intro can plausibly play under the source cue."""
        if from_track is None or to_track is None:
            return False

        def normalized(value: Any) -> str:
            return value.strip().casefold() if isinstance(value, str) else ""

        from_genre = normalized(from_track.genre)
        to_genre = normalized(to_track.genre)
        if not from_genre or from_genre != to_genre:
            return False

        from_subgenre = normalized(from_track.subgenre)
        to_subgenre = normalized(to_track.subgenre)
        if from_subgenre and from_subgenre == to_subgenre:
            return True

        comparable_deltas = []
        for field in ("energy", "danceability", "brightness", "noisiness"):
            source_value = getattr(from_track, field, None)
            target_value = getattr(to_track, field, None)
            if (
                isinstance(source_value, (int, float))
                and not isinstance(source_value, bool)
                and math.isfinite(source_value)
                and isinstance(target_value, (int, float))
                and not isinstance(target_value, bool)
                and math.isfinite(target_value)
            ):
                # Audio features are stored as FLOAT. Round away float32 storage
                # noise so the documented 0.20 boundary remains inclusive.
                comparable_deltas.append(round(abs(source_value - target_value), 4))
        return len(comparable_deltas) >= 3 and all(
            delta <= 0.20 for delta in comparable_deltas
        )

    def _item(self, pair: WordplayPair) -> Dict[str, Any]:
        data = pair.model_dump(mode="json", exclude={"normalized_keyword"})
        # Rows created before target_landing_timestamp existed keep exposing their
        # legacy to_timestamp as the landing cue.
        if data.get("target_landing_timestamp") is None:
            data["target_landing_timestamp"] = data.get("to_timestamp")
        from_track = self.session.get(Track, pair.from_track_id)
        to_track = self.session.get(Track, pair.to_track_id)
        data["from_track"] = self._track_dict(from_track) if from_track else None
        data["to_track"] = self._track_dict(to_track) if to_track else None
        bpm_delta_percent = self._bpm_delta_percent(from_track, to_track)
        data["bpm_delta_percent"] = bpm_delta_percent
        style_fit = self._style_fit(from_track, to_track)
        data["style_fit"] = style_fit
        cue_drumming = pair.source_cue_mode in {"cue_drumming", "cue_drumming_intro"}
        source_cue_fit = (
            self._cue_in_range(pair.from_timestamp, from_track)
            and (
                (
                    cue_drumming
                    and self._cue_in_range(pair.source_cue_end_timestamp, from_track)
                    and pair.from_timestamp < pair.source_cue_end_timestamp
                )
                or (not cue_drumming and pair.source_section_position == "end")
            )
        )
        landing = pair.target_landing_timestamp
        if landing is None:
            landing = pair.to_timestamp
        target_timing_fit = (
            self._cue_in_range(pair.target_intro_timestamp, to_track)
            and self._cue_in_range(landing, to_track)
            and pair.target_intro_timestamp < landing
            and (
                (cue_drumming and pair.target_section_position in {"start", "middle"})
                or (not cue_drumming and pair.target_section_position == "start")
            )
        )
        data["source_cue_fit"] = source_cue_fit
        data["target_timing_fit"] = target_timing_fit
        data["boundary_fit"] = (
            source_cue_fit
            and target_timing_fit
            and style_fit
            and bpm_delta_percent is not None
            and bpm_delta_percent <= 2.0
        )
        return data

    @staticmethod
    def _bpm_delta_percent(from_track: Optional[Track], to_track: Optional[Track]) -> Optional[float]:
        if from_track is None or to_track is None:
            return None
        from_bpm = from_track.bpm
        to_bpm = to_track.bpm
        if (
            from_bpm is None
            or to_bpm is None
            or not math.isfinite(from_bpm)
            or not math.isfinite(to_bpm)
            or from_bpm <= 0
            or to_bpm <= 0
        ):
            return None
        # Track BPM is stored as FLOAT; round away storage noise so an exact 2%
        # boundary is not rejected after a float32 round trip.
        return round(abs(to_bpm - from_bpm) / from_bpm * 100.0, 4)

    def list_pairs(
        self,
        status: Optional[str] = None,
        from_track_id: Optional[int] = None,
        query: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        if status is not None and status not in PAIR_STATUSES:
            raise WordplayValidationError("invalid status")
        if limit < 1 or limit > 500 or offset < 0:
            raise WordplayValidationError("invalid pagination")
        statement = select(WordplayPair)
        if status is not None:
            statement = statement.where(WordplayPair.status == status)
        if from_track_id is not None:
            statement = statement.where(WordplayPair.from_track_id == from_track_id)
        pairs = list(self.session.exec(statement.order_by(WordplayPair.id)).all())
        items = [self._item(pair) for pair in pairs]
        if query and query.strip():
            needle = query.strip().casefold()
            searchable = (
                "keyword",
                "source_phrase",
                "target_phrase",
                "transition_notes",
                "source_url",
            )

            def matches(item: Dict[str, Any]) -> bool:
                values = [str(item.get(key) or "") for key in searchable]
                for track_key in ("from_track", "to_track"):
                    track = item.get(track_key) or {}
                    values.extend(str(track.get(key) or "") for key in ("title", "artist", "album"))
                return any(needle in value.casefold() for value in values)

            items = [item for item in items if matches(item)]
        total = len(items)
        return {"items": items[offset : offset + limit], "total": total}

    def propose_pair(self, *, commit: bool = True, **values: Any) -> Dict[str, Any]:
        values = dict(values)
        supplied = set(values)
        allowed = {
            "from_track_id", "to_track_id", "keyword", "source_phrase", "target_phrase",
            "source_section_position", "target_section_position", "source_cue_mode",
            "from_timestamp", "source_cue_end_timestamp", "to_timestamp",
            "target_intro_timestamp", "target_landing_timestamp",
            "transition_notes", "source_url",
            "evidence_type", "verification_status",
        }
        unexpected = set(values) - allowed
        if unexpected:
            raise WordplayValidationError(f"unexpected fields: {', '.join(sorted(unexpected))}")
        values.setdefault("transition_notes", "")
        values.setdefault("source_url", "")
        values.setdefault("source_section_position", "unknown")
        values.setdefault("target_section_position", "unknown")
        values.setdefault("source_cue_mode", "section_end")
        values.setdefault("evidence_type", "hypothesis")
        values.setdefault("verification_status", "unverified")
        self._sync_target_landing_alias(values, supplied)
        for field in ("keyword", "source_phrase", "target_phrase", "transition_notes", "source_url"):
            if isinstance(values.get(field), str):
                values[field] = values[field].strip()
        self._validate_fields(values)
        normalized = self.normalize_keyword(values["keyword"])

        with db_lock:
            from_track, to_track = self._validate_tracks(
                values.get("from_track_id"), values.get("to_track_id")
            )
            self._validate_cues(values, from_track, to_track)
            existing = self.session.exec(
                select(WordplayPair).where(
                    WordplayPair.from_track_id == values["from_track_id"],
                    WordplayPair.to_track_id == values["to_track_id"],
                    WordplayPair.normalized_keyword == normalized,
                )
            ).first()
            if existing:
                return self._item(existing)
            pair = WordplayPair(
                **values,
                normalized_keyword=normalized,
                status="pending",
            )
            self.session.add(pair)
            try:
                self.session.flush()
                if commit:
                    self.session.commit()
                    self.session.refresh(pair)
            except Exception as exc:
                self.session.rollback()
                raise WordplayConflictError("wordplay pair conflicts with an existing proposal") from exc
            return self._item(pair)

    def approve_pair(self, pair_id: int) -> Optional[Dict[str, Any]]:
        with db_lock:
            pair = self.session.get(WordplayPair, pair_id)
            if pair is None:
                return None
            # Legacy approvals remain valid even though their boundary metadata
            # defaults to unknown. Only a pending -> approved transition is gated.
            if pair.status == "approved":
                return self._item(pair)
            self._validate_tracks(pair.from_track_id, pair.to_track_id)
            if not self._item(pair)["boundary_fit"]:
                raise WordplayValidationError(
                    "approval requires a usable source cue, ordered target intro and "
                    "landing timestamps, compatible musical style, and actual BPM "
                    "delta at or below 2%"
                )
            pair.status = "approved"
            pair.updated_at = datetime.now()
            self.session.add(pair)
            self.session.commit()
            self.session.refresh(pair)
            return self._item(pair)

    def update_pair(self, pair_id: int, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        supplied = set(changes)
        allowed = {
            "from_track_id", "to_track_id", "keyword", "source_phrase", "target_phrase",
            "source_section_position", "target_section_position", "source_cue_mode",
            "from_timestamp", "source_cue_end_timestamp", "to_timestamp",
            "target_intro_timestamp", "target_landing_timestamp",
            "transition_notes", "source_url",
            "evidence_type", "verification_status",
        }
        if not changes or set(changes) - allowed:
            raise WordplayValidationError("no valid fields to update")
        with db_lock:
            pair = self.session.get(WordplayPair, pair_id)
            if pair is None:
                return None
            merged = {field: getattr(pair, field) for field in allowed}
            merged.update(changes)
            self._sync_target_landing_alias(merged, supplied)
            for field in ("keyword", "source_phrase", "target_phrase", "transition_notes", "source_url"):
                if field in merged and merged[field] is not None:
                    merged[field] = merged[field].strip()
            self._validate_fields(merged)
            from_track, to_track = self._validate_tracks(
                merged["from_track_id"], merged["to_track_id"]
            )
            self._validate_cues(merged, from_track, to_track)
            transition_fields = {
                "from_track_id", "to_track_id", "keyword", "source_phrase", "target_phrase",
                "source_section_position", "target_section_position", "source_cue_mode",
                "from_timestamp", "source_cue_end_timestamp", "to_timestamp",
                "target_intro_timestamp", "target_landing_timestamp",
            }
            transition_changed = any(
                field in changes and merged[field] != getattr(pair, field)
                for field in transition_fields
            )
            if transition_changed:
                # A tested result applies to the exact versions, phrases, and cue points.
                # It cannot be carried into the same PATCH that changes those details.
                merged["verification_status"] = "unverified"
            for field, value in merged.items():
                setattr(pair, field, value)
            pair.normalized_keyword = self.normalize_keyword(pair.keyword)
            if set(changes) != {"verification_status"}:
                pair.status = "pending"
            pair.updated_at = datetime.now()
            self.session.add(pair)
            try:
                self.session.commit()
                self.session.refresh(pair)
            except Exception as exc:
                self.session.rollback()
                raise WordplayConflictError("wordplay pair conflicts with an existing proposal") from exc
            return self._item(pair)

    def delete_pair(self, pair_id: int) -> bool:
        with db_lock:
            pair = self.session.get(WordplayPair, pair_id)
            if pair is None:
                return False
            self.session.delete(pair)
            self.session.commit()
            return True
