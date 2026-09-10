"""Native Windows analysis: packaged FFmpeg, librosa and the same MusiCNN graph.

No WSL, Python installation or model download is required on the user's PC.
"""
from pathlib import Path
import subprocess
import sys

import numpy as np

from .analyzer import AudioAnalyzer
from . import constants
from utils.executables import find_ffmpeg


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
        import librosa
        self.librosa = librosa
        self.rhythm_extractor = self._rhythm
        self.key_extractor = self._key
        self.embedding_algo = True  # Graph is loaded only when embedding is requested.
        self._tf_session = None

    def _load_audio(self, filepath):
        converter = find_ffmpeg()
        if not converter:
            raise RuntimeError("同梱の音声デコーダーが見つかりません")
        decoded = subprocess.run(
            [converter, "-nostdin", "-v", "error", "-threads", "1", "-i", str(filepath),
             "-vn", "-ac", "1", "-ar", str(constants.SAMPLE_RATE), "-f", "f32le", "pipe:1"],
            capture_output=True, timeout=300, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        audio = np.frombuffer(decoded.stdout, dtype="<f4").copy()
        if not audio.size or not np.isfinite(audio).all():
            raise ValueError("Audio is empty or contains non-finite samples")
        return audio

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
        if self._tf_session is None:
            import tensorflow as tf
            root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
            model = root / "models" / "msd-musicnn-1.pb"
            graph_def = tf.compat.v1.GraphDef()
            graph_def.ParseFromString(model.read_bytes())
            graph = tf.Graph()
            with graph.as_default():
                tf.import_graph_def(graph_def, name="")
            self._tf_session = tf.compat.v1.Session(graph=graph, config=tf.compat.v1.ConfigProto(
                intra_op_parallelism_threads=1, inter_op_parallelism_threads=1, device_count={"GPU":0}))
            self._tf_input = graph.get_tensor_by_name("model/Placeholder:0")
            self._tf_output = graph.get_tensor_by_name("model/dense/BiasAdd:0")
            self._tf_training = graph.get_tensor_by_name("model/Placeholder_1:0")
        section = self._extract_loudest_section(audio, 60)
        section = self.librosa.resample(section, orig_sr=constants.SAMPLE_RATE, target_sr=16000)
        bands = musicnn_bands(section)
        if len(bands) < 187:
            bands = np.pad(bands, ((0,187-len(bands)),(0,0)), mode="wrap")
        patches = np.stack([bands[i:i+187] for i in range(0,len(bands)-186,93)])
        predictions = self._tf_session.run(self._tf_output, {self._tf_input:patches, self._tf_training:False})
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
