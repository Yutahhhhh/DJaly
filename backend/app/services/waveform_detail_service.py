"""Source-derived playback waveforms; disposable, bounded cache outside the DB."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import threading

import numpy as np
import platformdirs

SAMPLE_RATE = 24_000
BINS_PER_SECOND = 300
SAMPLES_PER_BIN = SAMPLE_RATE // BINS_PER_SECOND
MAX_SECONDS = 3600
CACHE_MAX_BYTES = 256 * 1024 * 1024
CACHE_MAX_FILES = 128
_workers = threading.BoundedSemaphore(2)
_locks = [threading.Lock() for _ in range(32)]
_cache_lock = threading.Lock()


class WaveformDetailError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _cache_dir() -> Path:
    return Path(platformdirs.user_cache_dir("plumdeck", "plumdeck")) / "waveform-detail-v1"


def _decode(filepath: Path) -> tuple[np.ndarray, int]:
    from utils.executables import find_ffmpeg
    decoder = find_ffmpeg()
    if not decoder:
        raise WaveformDetailError("詳細波形には FFmpeg が必要です。FFmpeg をインストールしてください。", 503)
    graph = (
        "[0:a:0]aformat=sample_fmts=flt:channel_layouts=mono,aresample=24000,"
        "asplit=4[full][lo][mi][hi];"
        "[lo]lowpass=f=250[low];[mi]highpass=f=250,lowpass=f=2500[mid];"
        "[hi]highpass=f=2500[high];"
        "[full][low][mid][high]join=inputs=4:channel_layout=quad:"
        "map=0.0-FL|1.0-FR|2.0-BL|3.0-BR[out]"
    )
    command = [decoder, "-nostdin", "-v", "error", "-threads", "1", "-i", str(filepath),
               "-filter_complex_threads", "1", "-filter_complex", graph, "-map", "[out]",
               "-t", str(MAX_SECONDS + 1), "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"]
    blocks: list[np.ndarray] = []
    samples = 0
    # A temporary stderr file avoids subprocess pipe deadlocks and unbounded RAM.
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            raise WaveformDetailError("波形デコーダーを起動できませんでした。", 503) from exc
        timed_out = threading.Event()

        def stop():
            timed_out.set()
            process.kill()

        timer = threading.Timer(120, stop)
        timer.start()
        try:
            assert process.stdout is not None
            pending = b""
            bin_bytes = SAMPLES_PER_BIN * 4 * 4
            while chunk := process.stdout.read(bin_bytes * BINS_PER_SECOND):
                pending += chunk
                count = len(pending) // bin_bytes * bin_bytes
                if not count:
                    continue
                audio = np.frombuffer(pending[:count], dtype="<f4").reshape(-1, SAMPLES_PER_BIN, 4)
                samples += audio.shape[0] * SAMPLES_PER_BIN
                if samples > MAX_SECONDS * SAMPLE_RATE:
                    raise WaveformDetailError("詳細波形は60分以内の音源に対応しています。")
                blocks.append(np.max(np.abs(audio), axis=1))
                pending = pending[count:]
            if pending:
                audio = np.frombuffer(pending, dtype="<f4").reshape(-1, 4)
                samples += len(audio)
                blocks.append(np.max(np.abs(audio), axis=0, keepdims=True))
            code = process.wait()
            if timed_out.is_set():
                raise WaveformDetailError("詳細波形の生成がタイムアウトしました。", 504)
            if code != 0:
                raise WaveformDetailError("音源をデコードできません。ファイル形式または破損を確認してください。")
            if not blocks or not samples:
                raise WaveformDetailError("音源に再生可能な音声がありません。")
            values = np.concatenate(blocks)
            if not np.isfinite(values).all():
                raise WaveformDetailError("音源に無効な音声サンプルがあります。")
            return np.rint(np.clip(values, 0, 1) * 255).astype(np.uint8), samples
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout:
                process.stdout.close()


def _prune_cache(directory: Path):
    entries = sorted(((p.stat().st_mtime_ns, p.stat().st_size, p) for p in directory.glob("*.npz")), reverse=True)
    used = 0
    for index, (_, size, path) in enumerate(entries):
        used += size
        if index >= CACHE_MAX_FILES or used > CACHE_MAX_BYTES:
            path.unlink(missing_ok=True)


def _downsample(values: np.ndarray, bins: int) -> np.ndarray:
    """Reduce to `bins` rows, keeping the peak of each group.

    Averaging would flatten transients, which is exactly what a waveform is for.
    """
    if bins <= 0 or bins >= len(values):
        return values
    edges = np.linspace(0, len(values), bins + 1).astype(int)
    return np.stack([values[start:max(stop, start + 1)].max(axis=0) for start, stop in zip(edges[:-1], edges[1:])])


def _payload(values: np.ndarray, samples: int, bins: int | None = None) -> dict:
    duration_ms = samples / SAMPLE_RATE * 1000
    reduced = _downsample(values, bins) if bins else values
    # A reduced payload still needs a density the client can map to time.
    bins_per_second = BINS_PER_SECOND if reduced is values else len(reduced) / (duration_ms / 1000)
    return {"bins_per_second": bins_per_second, "duration_ms": duration_ms,
            "amplitude_scale": 255, "source": "decoded-audio", "bands_hz": [250, 2500],
            "peaks": reduced[:, 0].tolist(), "low": reduced[:, 1].tolist(),
            "mid": reduced[:, 2].tolist(), "high": reduced[:, 3].tolist()}


def waveform_detail(filepath: str, bins: int | None = None) -> dict:
    source = Path(filepath).expanduser().resolve()
    try:
        stat = source.stat()
        if not source.is_file():
            raise FileNotFoundError()
    except OSError as exc:
        raise WaveformDetailError("音源ファイルが見つからないか、読み取れません。", 404) from exc
    identity = f"v1:{source}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"
    digest = hashlib.sha256(identity.encode()).hexdigest()
    directory = _cache_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WaveformDetailError("波形キャッシュに書き込めません。", 503) from exc
    target = directory / f"{digest}.npz"
    lock = _locks[int(digest[:2], 16) % len(_locks)]
    if not lock.acquire(timeout=125):
        raise WaveformDetailError("詳細波形を生成中です。しばらくして再試行してください。", 503)
    try:
        try:
            with np.load(target, allow_pickle=False) as stored:
                values, samples = stored["values"], int(stored["samples"])
                if values.ndim != 2 or values.shape[1] != 4 or values.dtype != np.uint8 or samples <= 0:
                    raise ValueError("Invalid cached waveform")
            target.touch()
            return _payload(values, samples, bins)
        except (OSError, ValueError, KeyError, EOFError):
            pass
        if not _workers.acquire(timeout=125):
            raise WaveformDetailError("詳細波形の生成が混み合っています。再試行してください。", 503)
        try:
            values, samples = _decode(source)
        finally:
            _workers.release()
        updated = source.stat()
        if (updated.st_size, updated.st_mtime_ns, updated.st_ctime_ns) != (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
            raise WaveformDetailError("音源が変更されました。詳細波形を再読み込みしてください。", 409)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                np.savez_compressed(output, values=values, samples=np.int64(samples))
            with _cache_lock:
                temporary.replace(target)
                _prune_cache(directory)
        except OSError:
            # The freshly decoded waveform remains usable if a disposable cache write fails.
            pass
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return _payload(values, samples, bins)
    finally:
        lock.release()
