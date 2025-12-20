import json
import asyncio
from typing import List, Dict, Any
from datetime import datetime
from sqlmodel import Session, select
from domain.models.track import Track, TrackAnalysis, TrackEmbedding
import infra.database.connection as db_connection

class IngestionRepository:
    def __init__(self):
        pass

    def _prepare_track_models(self, session: Session, result: Dict[str, Any], update_metadata: bool = True) -> None:
        filepath = result["filepath"]
        final_genre = result.get("genre", "Unknown")
        
        extras = result.get("features_extra", {})
        beat_positions = extras.get("beat_positions") or []
        waveform_peaks = extras.get("waveform_peaks") or []
        
        track_data = {
            "title": result.get("title", ""),
            "artist": result.get("artist", ""),
            "album": result.get("album", ""),
            "genre": final_genre,
            "bpm": result.get("bpm", 0),
            "key": result.get("key", ""),
            "scale": result.get("scale", ""),
            "duration": result.get("duration", 0),
            "energy": result.get("energy", 0.0),
            "danceability": result.get("danceability", 0.0),
            "brightness": result.get("brightness", 0.0),
            "contrast": result.get("contrast", 0.0),
            "noisiness": result.get("noisiness", 0.0),
            "loudness": result.get("loudness", -60.0),
            "loudness_range": float(result.get("loudness_range", 0.0)),
            "spectral_flux": float(result.get("spectral_flux", 0.0)),
            "spectral_rolloff": float(result.get("spectral_rolloff", 0.0)),
        }
        
        analysis_data = {
            "beat_positions": beat_positions,
            "waveform_peaks": waveform_peaks,
            "features_extra_json": json.dumps(extras)
        }

        existing_track = session.exec(select(Track).where(Track.filepath == filepath)).first()
        track_id = None

        if existing_track:
            track_id = existing_track.id
            if update_metadata:
                for k, v in track_data.items():
                    setattr(existing_track, k, v)
                session.add(existing_track)
        else:
            new_track = Track(filepath=filepath, **track_data)
            session.add(new_track)
            session.flush()
            session.refresh(new_track)
            track_id = new_track.id

        existing_analysis = session.get(TrackAnalysis, track_id)
        if existing_analysis:
            if analysis_data["beat_positions"]: existing_analysis.beat_positions = analysis_data["beat_positions"]
            if analysis_data["waveform_peaks"]: existing_analysis.waveform_peaks = analysis_data["waveform_peaks"]
            if extras and len(extras) > 0: existing_analysis.features_extra_json = analysis_data["features_extra_json"]
            session.add(existing_analysis)
        else:
            new_analysis = TrackAnalysis(track_id=track_id, **analysis_data)
            session.add(new_analysis)
        
        if "embedding" in result and result["embedding"]:
            embedding_data = result["embedding"]
            model_name = result.get("embedding_model", "musicnn")
            existing_embedding = session.get(TrackEmbedding, track_id)
            if existing_embedding:
                existing_embedding.embedding_json = json.dumps(embedding_data)
                existing_embedding.model_name = model_name
                existing_embedding.updated_at = datetime.now()
                session.add(existing_embedding)
            else:
                new_embedding = TrackEmbedding(
                    track_id=track_id, model_name=model_name, embedding_json=json.dumps(embedding_data)
                )
                session.add(new_embedding)

    def save_track(self, result: Dict[str, Any], update_metadata: bool = True):
        try:
            with Session(db_connection.engine) as session:
                self._prepare_track_models(session, result, update_metadata)
                session.commit()
        except Exception as e:
            print(f"ERROR: Save track failed: {e}")

    def _batch_save_tracks_sync(self, results: List[Dict[str, Any]]):
        try:
            with Session(db_connection.engine) as session:
                for result in results:
                    self._prepare_track_models(session, result, update_metadata=True)
                
                session.commit()
                print(f"INFO: Batch saved {len(results)} tracks.")

        except Exception as e:
            print(f"ERROR: Batch save failed: {e}")
            import traceback
            traceback.print_exc()

    async def batch_save_tracks(self, results: List[Dict[str, Any]]):
        if not results:
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._batch_save_tracks_sync, results)
