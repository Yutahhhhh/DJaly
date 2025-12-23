import os
import sys
import logging
import numpy as np
from typing import Optional, Dict, Any, Tuple, List, Union
from tinytag import TinyTag

from . import constants

# --- Environment Configuration ---
# Suppress TensorFlow C++ logs (Standard env var)
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3" 
# Limit threads for libraries to avoid contention in parallel processing
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

# Essentia Import
try:
    import essentia
    import essentia.standard as es
    HAS_ESSENTIA = True
except ImportError:
    HAS_ESSENTIA = False
    print("WARNING: Essentia not found.", flush=True)

logger = logging.getLogger(__name__)

class AudioAnalyzer:
    def __init__(self):
        if not HAS_ESSENTIA:
            raise ImportError("Essentia not found")
        self._init_algorithms()

    def _init_algorithms(self):
        """
        Initialize HEAVY algorithms only.
        """
        # Rhythm & Tonal
        self.rhythm_extractor = es.RhythmExtractor2013(method=constants.RHYTHM_METHOD)
        self.key_extractor = es.KeyExtractor(profileType=constants.KEY_PROFILE_TYPE)
        
        # Spectral & Energy
        self.rms_algo = es.RMS()
        self.danceability_algo = es.Danceability()
        self.centroid_algo = es.SpectralCentroidTime()
        self.zcr_algo = es.ZeroCrossingRate()
        self.spec_algo = es.Spectrum()
        self.w_algo = es.Windowing(type=constants.WINDOW_TYPE)
        self.rolloff_algo = es.RollOff()
        self.flux_algo = es.Flux()

        # Embedding Model (MusiCNN)
        # モデルファイルが存在する場合のみ初期化
        self.embedding_algo = None
        
        # Use path relative to this file to ensure it works regardless of CWD
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        model_path = os.path.join(base_dir, "models", "msd-musicnn-1.pb")
        
        if os.path.exists(model_path):
            try:
                # output="model/dense/BiasAdd" を指定して中間層(200次元)のベクトルを取得
                self.embedding_algo = es.TensorflowPredictMusiCNN(graphFilename=model_path, output="model/dense/BiasAdd")
                logger.info(f"MusiCNN model loaded from {model_path}")
            except Exception as e:
                logger.warning(f"Failed to load MusiCNN model: {e}")
        else:
            logger.warning(f"MusiCNN model not found at {model_path}. Embedding extraction will be skipped.")

    def analyze(self, filepath: str, skip_basic: bool = False, skip_waveform: bool = False) -> Optional[Dict[str, Any]]:
        if not HAS_ESSENTIA:
            return None

        filename = os.path.basename(filepath)
        
        try:
            tag = self._extract_metadata(filepath)
            if not tag: tag = TinyTag(None, 0)
            
            # Load Audio (Mono)
            audio = self._load_audio(filepath)
            if audio is None: return None

            result = {}
            
            # Basic Features (BPM, Key, Energy, etc.)
            if not skip_basic:
                features = self._extract_features(audio)
                result = self._format_result(filepath, tag, features)
            else:
                # 最小限のメタデータのみ設定
                year = None
                if tag.year:
                    try:
                        year = int(str(tag.year).strip()[:4])
                    except:
                        pass

                result = {
                    "filepath": filepath,
                    "title": tag.title or os.path.splitext(filename)[0],
                    "artist": tag.artist or "Unknown",
                    "album": tag.album or "Unknown",
                    "year": year,
                    "duration": tag.duration or 0.0,
                    "bpm": 0.0, # Dummy
                    "key": "",
                    "features_extra": {}
                }

            # Waveform Peaks
            if not skip_waveform:
                peaks = self._compute_waveform_peaks(audio, num_points=2000)
                if "features_extra" not in result: result["features_extra"] = {}
                result["features_extra"]["waveform_peaks"] = peaks

            # Embedding (MusiCNN)
            # 【Smart Windowing】
            # 静かなイントロやブレイクを避け、「曲の中で最も音圧(RMS)が高い60秒間」を
            # 自動検出してベクトル化する。これにより速度向上と精度向上を両立。
            if self.embedding_algo:
                try:
                    # 60秒あればジャンルやVibeの特定には十分
                    target_duration = 60 
                    
                    # 最もエナジーが高い区間を抽出
                    audio_for_embedding = self._extract_loudest_section(audio, target_duration)

                    # 推論実行
                    embeddings = self.embedding_algo(audio_for_embedding)
                    
                    if embeddings.ndim == 2:
                        mean_embedding = np.mean(embeddings, axis=0).tolist()
                        result["embedding"] = mean_embedding
                        result["embedding_model"] = "msd-musicnn-1"
                        
                except Exception as e:
                    logger.warning(f"Embedding extraction failed: {e}")

            log_msg = f"[PID:{os.getpid()}] DONE: {filename}"
            if not skip_basic:
                log_msg += f" (BPM:{result.get('bpm', 0)}, Key:{result.get('key', '')})"
            else:
                log_msg += " (Embedding Only)"
            print(log_msg, flush=True)
            
            return result

        except Exception as e:
            print(f"ERROR processing {filepath}: {e}", flush=True)
            return None

    def _extract_loudest_section(self, audio: np.ndarray, duration_sec: int) -> np.ndarray:
        """
        オーディオ全体から、RMS(音圧)が最も高い連続した区間を切り出す。
        これにより、ブレイクやイントロを避けて「サビ/ドロップ」を解析対象にできる。
        """
        sr = constants.SAMPLE_RATE
        target_samples = duration_sec * sr
        total_samples = len(audio)

        # 曲が指定秒数より短い場合はそのまま返す
        if total_samples <= target_samples:
            return audio

        # 高速化のため、1秒単位(sr)のホップサイズでRMSを粗くスキャンする
        # これにより計算コストは無視できるレベルになる
        hop_size = sr 
        frame_size = 2048 # RMS計算用のウィンドウサイズ
        
        # EssentiaのRMSアルゴリズムを使用 (FrameGeneratorで回す)
        rms_values = []
        for frame in es.FrameGenerator(audio, frameSize=frame_size, hopSize=hop_size, startFromZero=True):
            rms_values.append(self.rms_algo(frame))
        
        rms_array = np.array(rms_values).flatten()
        
        # 指定秒数分のウィンドウサイズ (1秒単位なので、秒数がそのままウィンドウサイズ)
        window_size = duration_sec 
        
        if len(rms_array) < window_size:
            return audio

        # 移動平均（畳み込み）を使って、区間合計が最大の開始点を探す
        # np.convolve は信号処理的に「窓をずらしながら合計」を計算する最速手段
        window = np.ones(int(window_size))
        # mode='valid' で境界からはみ出さないようにする
        energy_profile = np.convolve(rms_array, window, mode='valid')
        
        if len(energy_profile) == 0:
            # 念のためフォールバック: 中央を取る
            start_sample = (total_samples - target_samples) // 2
            return audio[start_sample : start_sample + target_samples]

        # 最大値のインデックス取得 (これが開始秒数に相当)
        start_sec_idx = np.argmax(energy_profile)
        
        # サンプル数に変換して切り出し
        start_sample = start_sec_idx * hop_size
        end_sample = start_sample + target_samples
        
        # 配列外参照ガード
        if end_sample > total_samples:
            end_sample = total_samples
            start_sample = max(0, end_sample - target_samples)
            
        return audio[start_sample:end_sample]

    def _compute_waveform_peaks(self, audio: np.ndarray, num_points: int = 2000) -> List[float]:
        """
        オーディオ全体の波形概形（ピーク）を計算する。
        """
        if len(audio) == 0:
            return []
            
        # データが要求ポイント数より少ない場合はそのまま返す
        if len(audio) <= num_points:
            return [float(abs(x)) for x in audio]

        # チャンクごとに最大振幅を抽出
        chunk_size = len(audio) // num_points
        # 端数切り捨てのためにリサイズ
        length = chunk_size * num_points
        reshaped = np.abs(audio[:length]).reshape(num_points, chunk_size)
        # 各チャンクの最大値を取得
        peaks = np.max(reshaped, axis=1)
        
        # JSONシリアライズ用にリスト変換 & 小数点丸め
        return [round(float(p), 4) for p in peaks]

    def _extract_metadata(self, filepath: str) -> Optional[TinyTag]:
        try:
            return TinyTag.get(filepath)
        except:
            return None

    def _load_audio(self, filepath: str) -> Optional[np.ndarray]:
        try:
            return es.MonoLoader(filename=filepath, sampleRate=constants.SAMPLE_RATE)()
        except:
            return None

    def _extract_features(self, audio: np.ndarray) -> Dict[str, Any]:
        bpm, ticks, confidence, _, _ = self.rhythm_extractor(audio)
        key, scale, key_strength = self.key_extractor(audio)
        
        loudness_algo = es.LoudnessEBUR128(sampleRate=constants.SAMPLE_RATE)
        stereo_audio = np.stack([audio, audio], axis=1)
        loudness_out = loudness_algo(stereo_audio)
        
        energy = np.mean(self.rms_algo(audio))
        danceability, _ = self.danceability_algo(audio)
        brightness = self.centroid_algo(audio)
        noisiness = np.mean(self.zcr_algo(audio))
        
        avg_rolloff, avg_flux = self._extract_spectral_features(audio)

        return {
            "bpm": bpm, 
            "beat_positions": ticks,
            "bpm_confidence": confidence,
            "key": key, 
            "scale": scale, 
            "key_strength": key_strength,
            "energy": energy, 
            "danceability": danceability,
            "loudness": loudness_out[2], 
            "loudness_range": loudness_out[3],
            "brightness": brightness, 
            "noisiness": noisiness,
            "rolloff": avg_rolloff, 
            "flux": avg_flux
        }

    def _extract_spectral_features(self, audio: np.ndarray) -> Tuple[float, float]:
        rolloff_values = []
        flux_values = []
        for frame in es.FrameGenerator(audio, frameSize=constants.FRAME_SIZE, hopSize=constants.HOP_SIZE, startFromZero=True):
            windowed = self.w_algo(frame)
            spec = self.spec_algo(windowed)
            if np.sum(spec) > 0.001: 
                rolloff_values.append(self.rolloff_algo(spec))
                flux_values.append(self.flux_algo(spec))

        avg_rolloff = float(np.percentile(rolloff_values, 85)) if rolloff_values else 0.0
        avg_flux = float(np.median(flux_values)) if flux_values else 0.0
        return avg_rolloff, avg_flux

    def _format_result(self, filepath: str, tag: TinyTag, features: Dict[str, Any]) -> Dict[str, Any]:
        def safe_scalar(val):
            if isinstance(val, (np.number, np.float32, np.float64)): return float(val)
            if isinstance(val, (np.integer, np.int32, np.int64)): return int(val)
            return val

        norm_energy = self._normalize(features['energy'], *constants.NORM_ENERGY)
        norm_danceability = self._normalize(features['danceability'], *constants.NORM_DANCEABILITY)
        norm_brightness = self._normalize(features['brightness'], *constants.NORM_BRIGHTNESS)
        norm_noisiness = self._normalize(features['noisiness'], *constants.NORM_NOISINESS)
        norm_flux = self._normalize(features['flux'], *constants.NORM_FLUX)
        norm_dyn = self._normalize(features['loudness_range'], *constants.NORM_LOUDNESS_RANGE)
        
        final_contrast = (norm_flux + norm_dyn) / 2.0
        detected_key = f"{features['key']} {features['scale']}"
        rounded_bpm = self._round_bpm(features['bpm'])
        
        beat_positions_list = features['beat_positions'].tolist() if isinstance(features['beat_positions'], np.ndarray) else []

        year = None
        if tag.year:
            try:
                year = int(str(tag.year).strip()[:4])
            except:
                pass

        return {
            "filepath": filepath,
            "title": tag.title or os.path.basename(filepath),
            "artist": tag.artist or "Unknown",
            "album": tag.album or "Unknown",
            "genre": tag.genre or "Unknown",
            "year": year,
            "duration": safe_scalar(tag.duration or 0.0),
            "bpm": rounded_bpm,
            "key": detected_key, 
            "scale": features['scale'],
            "energy": round(norm_energy, 2),
            "danceability": round(norm_danceability, 2),
            "brightness": round(norm_brightness, 2),
            "contrast": round(final_contrast, 2),
            "noisiness": round(norm_noisiness, 2),
            "loudness": round(safe_scalar(features['loudness']), 1),
            "loudness_range": safe_scalar(features['loudness_range']),
            "spectral_flux": safe_scalar(features['flux']),
            "spectral_rolloff": safe_scalar(features['rolloff']),
            "features_extra": {
                "loudness_range_db": round(safe_scalar(features['loudness_range']), 2),
                "spectral_flux_raw": round(safe_scalar(features['flux']), 2),
                "spectral_rolloff_hz": round(safe_scalar(features['rolloff']), 0),
                "bpm_confidence": round(safe_scalar(features['bpm_confidence']), 2),
                "key_strength": round(safe_scalar(features['key_strength']), 2),
                "bpm_raw": round(safe_scalar(features['bpm']), 2),
                "beat_positions": beat_positions_list
            }
        }

    def _round_bpm(self, bpm: float) -> float:
        return round(bpm * 2) / 2

    def _normalize(self, value: float, min_val: float, max_val: float) -> float:
        if isinstance(value, (np.ndarray, list)): value = float(np.mean(value))
        if max_val - min_val == 0: return 0.0
        norm = (float(value) - min_val) / (max_val - min_val)
        return max(0.0, min(1.0, norm))