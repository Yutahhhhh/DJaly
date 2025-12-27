import json
import asyncio
from typing import List, Dict, Any
from datetime import datetime
from sqlmodel import Session, select, text
from domain.models.track import Track, TrackAnalysis, TrackEmbedding
from domain.models.lyrics import Lyrics
import infra.database.connection as db_connection

class IngestionRepository:
    def __init__(self):
        pass

    def _prepare_track_models(self, session: Session, result: Dict[str, Any], update_metadata: bool = True) -> None:
        filepath = result["filepath"]
        
        track_update_data = {
            "title": result.get("title"), "artist": result.get("artist"),
            "album": result.get("album"), "genre": result.get("genre"), "year": result.get("year"),
            "bpm": result.get("bpm", 0), "key": result.get("key", ""), "scale": result.get("scale", ""),
            "duration": result.get("duration", 0), "energy": result.get("energy", 0.0),
            "danceability": result.get("danceability", 0.0), "brightness": result.get("brightness", 0.0),
            "contrast": result.get("contrast", 0.0), "noisiness": result.get("noisiness", 0.0),
            "loudness": result.get("loudness", -60.0),
            "loudness_range": float(result.get("loudness_range", 0.0)),
            "spectral_flux": float(result.get("spectral_flux", 0.0)),
            "spectral_rolloff": float(result.get("spectral_rolloff", 0.0)),
        }

        # PRAGMA foreign_keys は DuckDB で未サポートのため削除
        # 代わりに no_autoflush で ORM レベルの整合性チェックタイミングを調整
        with session.no_autoflush:
            existing_track = session.exec(select(Track).where(Track.filepath == filepath)).first()
            track_id = None

            if existing_track:
                track_id = existing_track.id
                if update_metadata:
                    for k, v in track_update_data.items():
                        if isinstance(v, str) and v and v.lower() != "unknown":
                            setattr(existing_track, k, v)
                        elif k in ["bpm", "energy", "danceability"] and isinstance(v, (int, float)) and v > 0:
                            setattr(existing_track, k, v)
                        elif k == "year" and isinstance(v, int) and v > 0:
                            setattr(existing_track, k, v)
            else:
                final_data = {}
                for k, v in track_update_data.items():
                    if k == "year":
                        final_data[k] = v if v is not None else None
                    else:
                        final_data[k] = v if v is not None else ""
                if not final_data.get("title"): final_data["title"] = "Unknown"
                if not final_data.get("artist"): final_data["artist"] = "Unknown"
                new_track = Track(filepath=filepath, **final_data)
                session.add(new_track)
                session.flush()
                track_id = new_track.id

            extras = result.get("features_extra", {})
            existing_analysis = session.get(TrackAnalysis, track_id) or TrackAnalysis(track_id=track_id)
            if extras: existing_analysis.features_extra_json = json.dumps(extras)
            if extras.get("beat_positions"): existing_analysis.beat_positions = extras["beat_positions"]
            if extras.get("waveform_peaks"): existing_analysis.waveform_peaks = extras["waveform_peaks"]
            session.add(existing_analysis)
            
            if "embedding" in result and result["embedding"]:
                emb = session.get(TrackEmbedding, track_id) or TrackEmbedding(track_id=track_id)
                emb.embedding_json = json.dumps(result["embedding"])
                emb.updated_at = datetime.now()
                session.add(emb)

            if "lyrics" in result and result["lyrics"]:
                ly = session.get(Lyrics, track_id) or Lyrics(track_id=track_id)
                if result["lyrics"].strip():
                    ly.content = result["lyrics"]
                    ly.updated_at = datetime.now()
                    session.add(ly)

    def save_track(self, result: Dict[str, Any], update_metadata: bool = True):
        try:
            with Session(db_connection.engine) as session:
                self._prepare_track_models(session, result, update_metadata)
                session.commit()
        except Exception as e:
            print(f"ERROR: Save track failed: {e}")

    async def batch_save_tracks(self, results: List[Dict[str, Any]]):
        if not results: return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._batch_save_tracks_sync, results)

    def _batch_save_tracks_sync(self, results: List[Dict[str, Any]]):
        try:
            with Session(db_connection.engine) as session:
                for result in results:
                    self._prepare_track_models(session, result, update_metadata=True)
                session.commit()
                print(f"INFO: Batch saved {len(results)} tracks.")
        except Exception as e:
            print(f"ERROR: Batch save failed: {e}")