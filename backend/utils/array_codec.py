"""
波形 / ビート位置など「1曲あたり数百〜数千点の数値配列」を DuckDB に
コンパクトなバイナリ (BLOB) で格納するためのエンコード/デコードヘルパー。

以前は JSON テキスト (`[0.1234, 0.2345, ...]`) を VARCHAR/JSON カラムに保存していたため
1曲あたり数十 KB になり、再解析のたびの UPDATE で DuckDB ファイルが肥大化していた。

- 波形ピーク: 0..1 の振幅 → 500 点にダウンサンプルし uint8 (1 バイト/点)
- ビート位置: 秒単位 (0..数百) で 10ms 精度が要る → float32 (4 バイト/点)
"""
from typing import List, Optional, Sequence

import numpy as np

WAVEFORM_POINTS = 500


def pack_u8_waveform(values: Optional[Sequence[float]], points: int = WAVEFORM_POINTS) -> Optional[bytes]:
    """0..1 の振幅列を最大 `points` 点へダウンサンプルし uint8 バイト列にする。"""
    if values is None:
        return None
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return b""
    arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
    if arr.size > points:
        chunk = arr.size // points
        arr = np.abs(arr[: chunk * points]).reshape(points, chunk).max(axis=1)
    arr = np.clip(arr, 0.0, 1.0)
    return (arr * 255.0 + 0.5).astype(np.uint8).tobytes()


def unpack_u8_waveform(blob: Optional[bytes]) -> List[float]:
    """`pack_u8_waveform` の逆。0..1 の float リストを返す。"""
    if not blob:
        return []
    return (np.frombuffer(blob, dtype=np.uint8).astype(np.float32) / 255.0).tolist()


def pack_f32(values: Optional[Sequence[float]]) -> Optional[bytes]:
    """float 列を float32 バイト列にする (ビート位置など)。"""
    if values is None:
        return None
    arr = np.asarray(values, dtype=np.float32)
    if arr.size == 0:
        return b""
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return arr.tobytes()


def unpack_f32(blob: Optional[bytes]) -> List[float]:
    """`pack_f32` の逆。"""
    if not blob:
        return []
    return np.frombuffer(blob, dtype=np.float32).astype(float).tolist()
