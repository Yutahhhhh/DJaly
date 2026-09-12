"""Native Windows analysis: packaged FFmpeg, librosa and MusiCNN via ONNX Runtime.

No WSL, Python installation or model download is required on the user's PC.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

from .analyzer import AudioAnalyzer
from . import constants
from . import light_dsp
from .progress import report
from utils.executables import find_ffmpeg


LIGHT_ANALYSIS_SECONDS = light_dsp.WINDOW_SECONDS


def musicnn_bands(audio: np.ndarray) -> np.ndarray:
    import librosa
    # Essentia TensorflowInputMusiCNN: centered 512-sample symmetric Hann,
    # 256 hop, Slaney area-normalized 96 mel power bands, log10(1+10000*x).
    padded = np.pad(np.asarray(audio, dtype=np.float32), (256, 256 + (-len(audio) % 256)))
    frames = np.lib.stride_tricks.sliding_window_view(padded, 512)[::256]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(512), axis=1)) ** 2
    mel = librosa.filters.mel(sr=16000, n_fft=512, n_mels=96, norm="slaney")
    return np.log10(1 + 10000 * (spectrum @ mel.T)).astype(np.float32)


class PortableAudioAnalyzer(AudioAnalyzer):
    def __init__(self):
        self.rhythm_extractor = self._rhythm
        self.key_extractor = self._key
        self.embedding_algo = True  # The model is loaded only when embedding is requested.
        self._embedding_session = None

    @property
    def librosa(self):
        # Light analysis must never import librosa/Numba, including during
        # construction in a fresh spawned or packaged worker.
        import librosa
        return librosa

    def _load_audio(self, filepath, max_seconds=1800):
        converter = find_ffmpeg()
        if not converter:
            raise RuntimeError("同梱の音声デコーダーが見つかりません")
        # Spool decoded PCM to disk instead of keeping stdout plus a second
        # NumPy copy in memory. Bound decoding before allocating the array.
        with tempfile.TemporaryFile() as pcm:
            decoded = subprocess.run(
                [converter, "-nostdin", "-v", "error", "-threads", "1", "-i", str(filepath),
                 "-t", str(max_seconds + 1), "-vn", "-ac", "1", "-ar", str(constants.SAMPLE_RATE),
                 "-f", "f32le", "pipe:1"],
                stdout=pcm, stderr=subprocess.PIPE, timeout=300, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if pcm.tell() > max_seconds * constants.SAMPLE_RATE * 4:
                raise ValueError("Audio analysis supports tracks up to 30 minutes")
            pcm.seek(0)
            audio = np.fromfile(pcm, dtype="<f4")
        if decoded.returncode:
            raise RuntimeError("音声をデコードできません: " + decoded.stderr.decode("utf-8", errors="replace")[-2000:])
        if not audio.size or not np.isfinite(audio).all():
            raise ValueError("Audio is empty or contains non-finite samples")
        return audio

    def _load_audio_segment(self, filepath, start_seconds=0.0, duration_seconds=LIGHT_ANALYSIS_SECONDS):
        """Decode only a representative window for latency-bounded analysis.

        Placing ``-ss`` before the input lets FFmpeg seek without decoding the
        preceding audio.  This is deliberately separate from ``_load_audio``:
        detailed analysis keeps its existing whole-track behaviour.
        """
        converter = find_ffmpeg()
        if not converter:
            raise RuntimeError("同梱の音声デコーダーが見つかりません")
        command = [converter, "-nostdin", "-v", "error", "-threads", "1"]
        if start_seconds > 0:
            command.extend(["-ss", f"{start_seconds:.3f}"])
        command.extend([
            "-i", str(filepath), "-t", str(duration_seconds), "-vn", "-ac", "1",
            "-ar", str(light_dsp.SAMPLE_RATE), "-f", "f32le", "pipe:1",
        ])
        decoded = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if decoded.returncode:
            raise RuntimeError(
                "音声をデコードできません: "
                + decoded.stderr.decode("utf-8", errors="replace")[-2000:]
            )
        audio = np.frombuffer(decoded.stdout, dtype="<f4").copy()
        maximum = int(duration_seconds * light_dsp.SAMPLE_RATE)
        if audio.size > maximum:
            audio = audio[:maximum]
        if not audio.size or not np.isfinite(audio).all():
            raise ValueError("Audio is empty or contains non-finite samples")
        return audio

    def _extract_light_features(self, audio, sample_rate=constants.SAMPLE_RATE):
        """Return inexpensive, finite descriptors from a bounded audio window."""
        rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
        loudness = float(20 * np.log10(max(rms, 1e-7)))
        if len(audio) > 1:
            noisiness = float(np.mean(np.signbit(audio[1:]) != np.signbit(audio[:-1])))
        else:
            noisiness = 0.0

        # A short FFT slice is enough for an approximate brightness/rolloff
        # indicator and avoids constructing a full-track STFT matrix.
        fft_samples = min(len(audio), sample_rate * 10)
        sample = audio[(len(audio) - fft_samples) // 2:][:fft_samples]
        frame_size, hop = 2048, 1024
        if len(sample) < frame_size:
            sample = np.pad(sample, (0, frame_size - len(sample)))
        frames = np.lib.stride_tricks.sliding_window_view(sample, frame_size)[::hop]
        spectra = np.abs(np.fft.rfft(frames * np.hanning(frame_size), axis=1))
        spectrum = np.mean(spectra, axis=0)
        frequencies = np.fft.rfftfreq(frame_size, 1 / sample_rate)
        total = float(np.sum(spectrum))
        brightness = float(np.dot(spectrum, frequencies) / total) if total > 0 else 0.0
        if total > 0:
            rolloff_index = int(np.searchsorted(np.cumsum(spectrum), total * .85))
            rolloff = float(frequencies[min(rolloff_index, len(frequencies) - 1)])
        else:
            rolloff = 0.0

        frame_rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
        frame_db = 20 * np.log10(np.maximum(frame_rms, 1e-7))
        active_db = frame_db[frame_db > max(-70, float(np.max(frame_db)) - 20)]
        loudness_range = float(np.percentile(active_db, 95) - np.percentile(active_db, 10)) if active_db.size else 0.0
        normalized_spectra = spectra / np.maximum(np.sum(spectra, axis=1, keepdims=True), 1e-8)
        flux = float(np.median(np.sqrt(np.sum(np.diff(normalized_spectra, axis=0) ** 2, axis=1)))) if len(normalized_spectra) > 1 else 0.0
        contrast = float(np.clip((flux / constants.NORM_FLUX[1]
                                  + loudness_range / constants.NORM_LOUDNESS_RANGE[1]) / 2, 0, 1))
        return {
            "energy": float(np.clip(rms / constants.NORM_ENERGY[1], 0, 1)),
            "brightness": float(np.clip(
                (brightness - constants.NORM_BRIGHTNESS[0])
                / (constants.NORM_BRIGHTNESS[1] - constants.NORM_BRIGHTNESS[0]), 0, 1,
            )),
            "noisiness": float(np.clip(noisiness / constants.NORM_NOISINESS[1], 0, 1)),
            "loudness": round(loudness, 1),
            "loudness_range": loudness_range,
            "spectral_flux": flux,
            "spectral_rolloff": rolloff,
            "contrast": contrast,
        }

    def analyze_light(self, filepath, external_lyrics=None):
        """Windows speed-first analysis without full decode or MusiCNN."""
        report("metadata", "曲名・長さなどの音源情報を読み取っています")
        tag = self._extract_metadata(filepath)
        duration = float(getattr(tag, "duration", 0) or 0)
        start = max(0.0, (duration - LIGHT_ANALYSIS_SECONDS) / 2) if duration else 0.0
        report("decode", f"代表区間を読み込んでいます（最大{LIGHT_ANALYSIS_SECONDS}秒）")
        audio = self._load_audio_segment(filepath, start, LIGHT_ANALYSIS_SECONDS)
        report("rhythm_key", "BPM・キーを軽量推定しています")
        bpm, confidence, key, scale, key_strength = light_dsp.rhythm_and_key(audio)
        if not np.isfinite(bpm) or bpm <= 0:
            raise ValueError("軽量解析でBPMを取得できませんでした")

        extra = {
            "analysis_level": "light",
            "analysis_profile": "light",
            "analysis_window_start_seconds": round(start, 3),
            "analysis_window_seconds": round(len(audio) / light_dsp.SAMPLE_RATE, 3),
            "analysis_sample_rate": light_dsp.SAMPLE_RATE,
            "analysis_components": {
                "rhythm": "numpy-autocorrelation-light-v2",
                "key": "numpy-chroma-light-v2",
                "timbre": "bounded-summary-v2",
            },
            "bpm_confidence": round(float(confidence), 2),
            "key_strength": round(float(key_strength), 2),
            # Beat timestamps from a middle excerpt are not a valid whole-track
            # playback grid.  Keep the estimate explicit instead of faking one.
            "playback_grid_estimated": True,
        }
        metadata = tag
        report("timbre", "音量・明るさなどの基本情報を計算しています")
        result = {
            "filepath": str(filepath),
            "title": ((getattr(metadata, "title", None) or "").strip()
                      or Path(filepath).stem),
            "artist": (getattr(metadata, "artist", None) or "Unknown").strip(),
            "album": (getattr(metadata, "album", None) or "Unknown").strip(),
            "genre": (getattr(metadata, "genre", None) or "Unknown").strip(),
            "year": None,
            "lyrics": external_lyrics or (
                metadata.extra.get("lyrics") if metadata and hasattr(metadata, "extra") else None
            ),
            "duration": duration,
            "bpm": round(float(bpm), 2),
            "key": f"{key} {scale}",
            "scale": scale,
            # A bounded beat-stability estimate is safer than storing an
            # unknown value as the genuine minimum of the feature.
            "danceability": float(np.clip(confidence, 0, 1)),
            "analysis_level": "light",
            "features_extra": extra,
            **self._extract_light_features(audio, sample_rate=light_dsp.SAMPLE_RATE),
        }
        raw_year = getattr(metadata, "year", None)
        year_prefix = str(raw_year).strip()[:4] if raw_year else ""
        if year_prefix.isdigit():
            result["year"] = int(year_prefix)
        return result

    def _rhythm(self, audio):
        y = self.librosa.resample(audio, orig_sr=constants.SAMPLE_RATE, target_sr=22050)
        envelope = self.librosa.onset.onset_strength(y=y, sr=22050, hop_length=256)
        tempo, frames = self.librosa.beat.beat_track(onset_envelope=envelope, sr=22050, hop_length=256)
        ticks = self.librosa.frames_to_time(frames, sr=22050, hop_length=256)
        bpm = float(np.asarray(tempo).reshape(-1)[0])
        intervals = np.diff(ticks)
        confidence = float(np.clip(1 - np.std(intervals) / max(np.mean(intervals), 1e-8), 0, 1)) if intervals.size else 0.0
        return bpm, ticks, confidence, np.array([]), intervals

    def _key(self, audio):
        y = self.librosa.resample(audio, orig_sr=constants.SAMPLE_RATE, target_sr=22050)
        chroma = self.librosa.feature.chroma_stft(y=y, sr=22050).mean(axis=1)
        major = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
        minor = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
        centered = chroma - chroma.mean()
        scores = []
        for profile in (major, minor):
            profile = profile - profile.mean()
            scores.extend(float(np.dot(centered, np.roll(profile, key)) / max(np.linalg.norm(centered)*np.linalg.norm(profile), 1e-8)) for key in range(12))
        best = int(np.argmax(scores))
        return ["C","C#","D","Eb","E","F","F#","G","Ab","A","Bb","B"][best % 12], "major" if best < 12 else "minor", max(0.0, scores[best])

    def _extract_loudest_section(self, audio, duration_sec):
        count = constants.SAMPLE_RATE * duration_sec
        if len(audio) <= count:
            return audio
        hop = constants.SAMPLE_RATE
        rms = np.array([np.sqrt(np.mean(audio[i:i+2048]**2)) for i in range(0, len(audio), hop)])
        start = int(np.argmax(np.convolve(rms, np.ones(duration_sec), mode="valid"))) * hop
        return audio[start:start+count]

    def _extract_embedding(self, audio):
        if self._embedding_session is None:
            import onnxruntime as ort
            root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
            model = root / "models" / "msd-musicnn-1.onnx"
            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            self._embedding_session = ort.InferenceSession(
                str(model), sess_options=options, providers=["CPUExecutionProvider"])
        section = self._extract_loudest_section(audio, 60)
        section = self.librosa.resample(section, orig_sr=constants.SAMPLE_RATE, target_sr=16000)
        bands = musicnn_bands(section)
        if len(bands) < 187:
            bands = np.pad(bands, ((0,187-len(bands)),(0,0)), mode="wrap")
        patches = np.stack([bands[i:i+187] for i in range(0,len(bands)-186,93)])
        predictions = self._embedding_session.run(
            ["embeddings"], {"melspectrogram": patches})[0]
        vector = np.mean(predictions, axis=0)
        if vector.shape != (200,) or not np.isfinite(vector).all() or not np.linalg.norm(vector):
            raise ValueError("MusiCNN produced an invalid embedding")
        return {"embedding": vector.tolist(), "embedding_model": constants.EMBEDDING_MODEL,
                "features_extra": {"embedding_sample_rate":16000, "embedding_pipeline_version":constants.EMBEDDING_PIPELINE_VERSION}}

    def _extract_timbre_features(self, audio):
        import pyloudnorm
        spectrum = np.abs(self.librosa.stft(audio, n_fft=2048, hop_length=1024))
        rms = self.librosa.feature.rms(S=spectrum)[0]
        flux = np.sqrt(np.sum(np.diff(spectrum, axis=1)**2, axis=0))
        rolloff = self.librosa.feature.spectral_rolloff(S=spectrum, sr=constants.SAMPLE_RATE)[0]
        loudness = pyloudnorm.Meter(constants.SAMPLE_RATE).integrated_loudness(
            np.pad(audio, (0, max(0, int(constants.SAMPLE_RATE*.4)+1-len(audio)))))
        loudness = float(loudness) if np.isfinite(loudness) else -70.0
        levels = 20*np.log10(np.maximum(rms, 1e-7))
        active = levels[levels > max(-70, float(np.max(levels))-20)]
        spread = float(np.percentile(active,95)-np.percentile(active,10)) if active.size else 0.0
        envelope = self.librosa.onset.onset_strength(S=self.librosa.amplitude_to_db(spectrum))
        correlation = self.librosa.autocorrelate(envelope, max_size=min(128,len(envelope)))
        periodicity = float(np.max(correlation[4:])/max(correlation[0],1e-8)) if len(correlation)>4 else 0.0
        return {"energy":float(np.sqrt(np.mean(audio**2))), "danceability":2.5*np.clip(periodicity,0,1),
                "brightness":float(self.librosa.feature.spectral_centroid(S=spectrum, sr=constants.SAMPLE_RATE).mean()),
                "noisiness":float(self.librosa.feature.zero_crossing_rate(audio).mean()),
                "loudness":loudness,"loudness_range":spread,
                "rolloff":float(np.percentile(rolloff,85)),"flux":float(np.median(flux)) if flux.size else 0.0}
