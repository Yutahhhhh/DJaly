import os
import sys
import logging
import numpy as np
from typing import Optional, Dict, Any, Tuple, List, Union
from tinytag import TinyTag
from . import constants

# Essentia Import
try:
    import essentia
    import essentia.standard as es
    HAS_ESSENTIA = True
except ImportError:
    HAS_ESSENTIA = False

logger = logging.getLogger(__name__)

class AudioAnalyzer:
    def __init__(self):
        if not HAS_ESSENTIA:
            raise ImportError("Essentia not found")
        self._init_algorithms()

    def _init_algorithms(self):
        self.rhythm_extractor = es.RhythmExtractor2013(method=constants.RHYTHM_METHOD)
        self.key_extractor = es.KeyExtractor(profileType=constants.KEY_PROFILE_TYPE)
        self.rms_algo = es.RMS()
        self.danceability_algo = es.Danceability()
        self.centroid_algo = es.SpectralCentroidTime()
        self.zcr_algo = es.ZeroCrossingRate()
        self.spec_algo = es.Spectrum()
        self.w_algo = es.Windowing(type=constants.WINDOW_TYPE)
        self.rolloff_algo = es.RollOff()
        self.flux_algo = es.Flux()
        self.embedding_algo = None
        
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        model_path = os.path.join(base_dir, "models", "msd-musicnn-1.pb")
        
        if os.path.exists(model_path):
            try:
                self.embedding_algo = es.TensorflowPredictMusiCNN(graphFilename=model_path, output="model/dense/BiasAdd")
            except Exception as e:
                logger.warning(f"Failed to load MusiCNN: {e}")

    def analyze(self, filepath: str, skip_basic: bool = False, skip_waveform: bool = False, external_lyrics: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not HAS_ESSENTIA: return None
        filename = os.path.basename(filepath)

        try:
            tag = self._extract_metadata(filepath) or TinyTag(None, 0)
            audio = self._load_audio(filepath)
            if audio is None: return None

            result = {}
            if not skip_basic:
                features = self._extract_features(audio)
                # 確実に引数を渡す
                result = self._format_result(filepath, tag, features, external_lyrics=external_lyrics)
            else:
                # skip_basic時の辞書構築 (NameErrorを防止)
                year_val = None
                if tag.year:
                    try: year_val = int(str(tag.year).strip()[:4])
                    except: pass
                
                # 歌詞の特定
                lyrics_final = external_lyrics if external_lyrics else (tag.extra.get('lyrics') if hasattr(tag, 'extra') else None)
                
                result = {
                    "filepath": filepath,
                    "title": (tag.title or "").strip() or os.path.splitext(filename)[0],
                    "artist": (tag.artist or "").strip() or "Unknown",
                    "album": (tag.album or "").strip() or "Unknown",
                    "year": year_val,
                    "duration": tag.duration or 0.0,
                    "bpm": 0.0,
                    "key": "",
                    "lyrics": lyrics_final,
                    "features_extra": {}
                }

            if not skip_waveform:
                peaks = self._compute_waveform_peaks(audio, num_points=500)
                if "features_extra" not in result: result["features_extra"] = {}
                result["features_extra"]["waveform_peaks"] = peaks

            if self.embedding_algo:
                try:
                    embedding = self._extract_embedding(audio)
                    result.update({k: v for k, v in embedding.items() if k != "features_extra"})
                    result.setdefault("features_extra", {}).update(embedding["features_extra"])
                except Exception as e:
                    logger.warning(f"Embedding failed: {e}")

            return result
        except Exception as e:
            print(f"ERROR processing {filepath}: {e}", flush=True)
            return None

    def _extract_embedding(self, audio: np.ndarray) -> Dict[str, Any]:
        if self.embedding_algo is None:
            raise RuntimeError("MusiCNN model is unavailable")
        section = self._extract_loudest_section(audio, 60)
        section = es.Resample(inputSampleRate=constants.SAMPLE_RATE,
                              outputSampleRate=constants.EMBEDDING_SAMPLE_RATE, quality=1)(section)
        embeddings = self.embedding_algo(section)
        if embeddings.ndim != 2 or not embeddings.size or not np.isfinite(embeddings).all():
            raise ValueError("MusiCNN returned invalid embeddings")
        return {
            "embedding": np.mean(embeddings, axis=0).tolist(),
            "embedding_model": constants.EMBEDDING_MODEL,
            "features_extra": {
                "embedding_sample_rate": constants.EMBEDDING_SAMPLE_RATE,
                "embedding_pipeline_version": constants.EMBEDDING_PIPELINE_VERSION,
            },
        }

    def analyze_selected(self, filepath: str, features: List[str]) -> Dict[str, Any]:
        """Read audio once and compute only requested components; never read/write tags."""
        if not features or set(features) - constants.COMPONENT_VERSIONS.keys():
            raise ValueError("Unknown or empty analysis components")
        audio = self._load_audio(filepath)
        if audio is None or not len(audio):
            raise ValueError("Audio could not be decoded")
        result: Dict[str, Any] = {"features_extra": {}}
        extra = result["features_extra"]
        if "embedding" in features:
            embedding = self._extract_embedding(audio)
            extra.update(embedding.pop("features_extra"))
            result.update(embedding)
        if "rhythm" in features:
            bpm, ticks, confidence, _, _ = self.rhythm_extractor(audio)
            result["bpm"] = round(float(bpm), 2)
            extra.update(bpm_confidence=float(confidence), beat_positions=ticks.tolist())
        if "key" in features:
            key, scale, strength = self.key_extractor(audio)
            result.update(key=f"{key} {scale}", scale=scale)
            extra["key_strength"] = float(strength)
        if "waveform" in features:
            extra["waveform_peaks"] = self._compute_waveform_peaks(audio, 500)
        if "timbre" in features:
            raw = self._extract_timbre_features(audio)
            def norm(value, bounds):
                return round(float(np.clip((value - bounds[0]) / (bounds[1] - bounds[0]), 0, 1)), 2)
            result.update(
                energy=norm(raw["energy"], constants.NORM_ENERGY),
                danceability=norm(raw["danceability"], constants.NORM_DANCEABILITY),
                brightness=norm(raw["brightness"], constants.NORM_BRIGHTNESS),
                noisiness=norm(raw["noisiness"], constants.NORM_NOISINESS),
                contrast=round((norm(raw["flux"], constants.NORM_FLUX) + norm(raw["loudness_range"], constants.NORM_LOUDNESS_RANGE)) / 2, 2),
                loudness=round(float(raw["loudness"]), 1), loudness_range=float(raw["loudness_range"]),
                spectral_flux=float(raw["flux"]), spectral_rolloff=float(raw["rolloff"]),
            )
        extra["analysis_components"] = {f: constants.COMPONENT_VERSIONS[f] for f in features}
        return result

    def _extract_loudest_section(self, audio: np.ndarray, duration_sec: int) -> np.ndarray:
        sr = constants.SAMPLE_RATE
        target_samples = duration_sec * sr
        if len(audio) <= target_samples: return audio
        hop_size = sr
        rms_values = [self.rms_algo(frame) for frame in es.FrameGenerator(audio, frameSize=2048, hopSize=hop_size)]
        rms_array = np.array(rms_values).flatten()
        if len(rms_array) < duration_sec: return audio
        window = np.ones(int(duration_sec))
        energy_profile = np.convolve(rms_array, window, mode='valid')
        start_sample = np.argmax(energy_profile) * hop_size
        return audio[start_sample : start_sample + target_samples]

    def _compute_waveform_peaks(self, audio: np.ndarray, num_points: int = 2000) -> List[float]:
        if len(audio) == 0: return []
        if len(audio) <= num_points: return [round(float(abs(x)), 4) for x in audio]
        chunk_size = len(audio) // num_points
        reshaped = np.abs(audio[:chunk_size * num_points]).reshape(num_points, chunk_size)
        return [round(float(p), 4) for p in np.max(reshaped, axis=1)]

    def _extract_metadata(self, filepath: str) -> Optional[TinyTag]:
        try: return TinyTag.get(filepath)
        except: return None

    def _load_audio(self, filepath: str) -> Optional[np.ndarray]:
        try: return es.MonoLoader(filename=filepath, sampleRate=constants.SAMPLE_RATE)()
        except: return None

    def _extract_features(self, audio: np.ndarray) -> Dict[str, Any]:
        bpm, ticks, confidence, _, _ = self.rhythm_extractor(audio)
        key, scale, key_strength = self.key_extractor(audio)
        return {
            "bpm": bpm, "beat_positions": ticks, "bpm_confidence": confidence,
            "key": key, "scale": scale, "key_strength": key_strength,
            **self._extract_timbre_features(audio),
        }

    def _extract_timbre_features(self, audio: np.ndarray) -> Dict[str, Any]:
        loudness_algo = es.LoudnessEBUR128(sampleRate=constants.SAMPLE_RATE)
        loudness_out = loudness_algo(np.stack([audio, audio], axis=1))
        
        rolloff_values, flux_values = [], []
        for frame in es.FrameGenerator(audio, frameSize=constants.FRAME_SIZE, hopSize=constants.HOP_SIZE):
            spec = self.spec_algo(self.w_algo(frame))
            if np.sum(spec) > 0.001:
                rolloff_values.append(self.rolloff_algo(spec))
                flux_values.append(self.flux_algo(spec))

        return {
            "energy": np.mean(self.rms_algo(audio)),
            "danceability": self.danceability_algo(audio)[0],
            "brightness": self.centroid_algo(audio),
            "noisiness": np.mean(self.zcr_algo(audio)),
            "loudness": loudness_out[2], "loudness_range": loudness_out[3],
            "rolloff": float(np.percentile(rolloff_values, 85)) if rolloff_values else 0.0,
            "flux": float(np.median(flux_values)) if flux_values else 0.0
        }

    def _format_result(self, filepath: str, tag: TinyTag, features: Dict[str, Any], external_lyrics: Optional[str] = None) -> Dict[str, Any]:
        def safe_s(v): return float(v) if isinstance(v, (np.number, float, int)) else v
        def norm(v, min_v, max_v): return max(0.0, min(1.0, (float(v) - min_v) / (max_v - min_v))) if max_v != min_v else 0.0

        # 正確な変数名で処理
        lyrics_val = external_lyrics if external_lyrics else (tag.extra.get('lyrics') if hasattr(tag, 'extra') else None)
        
        return {
            "filepath": filepath,
            "title": (tag.title or "").strip() or os.path.splitext(os.path.basename(filepath))[0],
            "artist": (tag.artist or "Unknown").strip(),
            "album": (tag.album or "Unknown").strip(),
            "genre": (tag.genre or "Unknown").strip(),
            "year": int(str(tag.year).strip()[:4]) if tag.year and str(tag.year).strip()[:4].isdigit() else None,
            "lyrics": lyrics_val,
            "duration": safe_s(tag.duration or 0.0),
            "bpm": round(float(features['bpm']), 2),
            "key": f"{features['key']} {features['scale']}",
            "scale": features['scale'],
            "energy": round(norm(features['energy'], *constants.NORM_ENERGY), 2),
            "danceability": round(norm(features['danceability'], *constants.NORM_DANCEABILITY), 2),
            "brightness": round(norm(features['brightness'], *constants.NORM_BRIGHTNESS), 2),
            "contrast": round((norm(features['flux'], *constants.NORM_FLUX) + norm(features['loudness_range'], *constants.NORM_LOUDNESS_RANGE)) / 2.0, 2),
            "noisiness": round(norm(features['noisiness'], *constants.NORM_NOISINESS), 2),
            "loudness": round(safe_s(features['loudness']), 1),
            "loudness_range": safe_s(features['loudness_range']),
            "spectral_flux": safe_s(features['flux']),
            "spectral_rolloff": safe_s(features['rolloff']),
            "features_extra": {
                "bpm_confidence": round(safe_s(features['bpm_confidence']), 2),
                "key_strength": round(safe_s(features['key_strength']), 2),
                "beat_positions": features['beat_positions'].tolist() if hasattr(features['beat_positions'], 'tolist') else []
            }
        }
