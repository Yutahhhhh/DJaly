"""Smoke a packaged backend using an isolated temporary DB, never the user DB.

PYTHONPATH=backend backend/.venv/bin/python backend/tests/grid_packaged_probe.py \
    backend/dist/plumdeck-server
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave


def request(base, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=150) as response:
        return json.load(response)


def main():
    executable = Path(sys.argv[1]).resolve()
    source = request("http://127.0.0.1:48123", "/api/tracks?offset=0&limit=1")[0]
    with tempfile.TemporaryDirectory(prefix="plumdeck-packaged-grid-") as directory:
        root = Path(directory)
        os.environ["DB_PATH"] = str(root / "test.duckdb")
        os.environ["USER_DATA_DIR"] = str(root)
        from sqlmodel import Session, create_engine
        from infra.database.schema import init_raw_db
        from domain.models.track import Track
        from infra.rekordbox_grid import find_analysis, read_grid
        import numpy as np

        sr = 44100
        audio = np.zeros(sr * 24, dtype=np.float32)
        pulse = np.random.default_rng(42).standard_normal(1323) * np.exp(-np.arange(1323) / 220)
        pulse /= np.max(np.abs(pulse))
        for onset in np.arange(0.137, 23.96, 0.5):
            start = round(onset * sr)
            audio[start:start + len(pulse)] = pulse * 0.8
        audio_path = root / "click.wav"
        with wave.open(str(audio_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sr)
            output.writeframes((audio * 32767).astype("<i2").tobytes())
        engine = create_engine("duckdb:///" + os.environ["DB_PATH"])
        init_raw_db(engine)
        with Session(engine) as session:
            session.add(Track(id=1, filepath=source["filepath"], title="Source probe", artist="Probe",
                              genre="Unknown", bpm=source["bpm"], duration=source["duration"]))
            session.add(Track(id=2, filepath=str(audio_path), title="Synthetic probe", artist="Probe",
                              genre="Unknown", bpm=0, duration=24))
            session.commit()
        engine.dispose()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        environment = dict(os.environ, PLUMDECK_PORT=str(port), PYTHONUNBUFFERED="1")
        base = f"http://127.0.0.1:{port}"
        log_path = root / "server.log"
        with log_path.open("w+") as log:
            process = subprocess.Popen([str(executable)], env=environment, stdout=log, stderr=log)
            try:
                start = time.monotonic()
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Packaged backend exited during startup")
                    try:
                        request(base, "/api/tracks?limit=1")
                        break
                    except OSError:
                        if time.monotonic() - start > 180:
                            raise TimeoutError("Packaged backend startup timed out")
                        time.sleep(0.25)
                print(json.dumps({"started": True, "isolated_port": port}), flush=True)
                original = read_grid(find_analysis(source["filepath"])[0])
                imported = request(base, "/api/tracks/1/performance-metadata")
                assert imported["revision"] == 0
                assert imported["beat_grid"] == original.model_dump()
                restored = request(base, "/api/tracks/1/grid-rekordbox", {})
                assert restored == imported["beat_grid"]
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(request, base, "/api/tracks/2/grid-analysis", {"force": True})
                    time.sleep(0.1)
                    start = time.monotonic()
                    request(base, "/api/tracks?limit=1")
                    responsive_seconds = time.monotonic() - start
                    analyzed = future.result(timeout=150)
                assert analyzed["source"] == "analysis"
                assert len(analyzed["beat_times_ms"]) >= 40
                assert analyzed["first_beat_ms"] > 0
                assert abs(analyzed["bpm"] - 120) < 2
                assert request(base, "/api/tracks/2/grid-analysis", {"force": False}) == analyzed
                assert request(base, "/api/tracks/2/performance-metadata")["revision"] == 0
                assert request(base, "/api/tracks/1/performance-metadata") == imported
                assert responsive_seconds < 2
                print(json.dumps({"packaged_source_exact_beats": len(original.beat_times_ms),
                                  "source_first_ms": original.first_beat_ms,
                                  "forced_analysis_bpm": analyzed["bpm"],
                                  "analysis_beats": len(analyzed["beat_times_ms"]),
                                  "concurrent_request_seconds": round(responsive_seconds, 3),
                                  "manual_revision": 0}), flush=True)
            except Exception:
                log.flush()
                print(log_path.read_text()[-6000:], file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
