"""Real decoder/grid/API acceptance, outside pytest's global DSP mocks.

Pass local audio paths as arguments. Only temporary copies and a fresh database
are written. The output bundle can also drive native and browser acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tracks", nargs="+")
    parser.add_argument("--serve", type=int, help="Serve the isolated API after verification")
    args = parser.parse_args()
    directory = Path(tempfile.mkdtemp(prefix="plumdeck-real-grid-"))
    os.environ["DB_PATH"] = str(directory / "library.duckdb")
    os.environ["USER_DATA_DIR"] = str(directory)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fastapi.middleware.cors import CORSMiddleware
    from sqlmodel import Session
    from infra.database.connection import engine
    from infra.database.schema import init_raw_db
    from domain.models.track import Track
    from api.routers.performance_metadata import router
    from api.routers.waveform_detail import router as waveform_router

    init_raw_db(engine)
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:1420"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    app.include_router(waveform_router)
    bundle = []
    with TestClient(app) as client:
        for index, filename in enumerate(args.tracks):
            source = Path(filename).resolve(strict=True)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            copy = directory / (str(index) + source.suffix)
            shutil.copy2(source, copy)
            info = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(copy)
            ]))
            duration = float(info["format"]["duration"])
            assert duration > 10, "Use complete songs, not short sound effects"
            with Session(engine) as session:
                track = Track(filepath=str(copy), title=source.stem, artist="Local acceptance", genre="", bpm=120, duration=duration)
                session.add(track)
                session.commit()
                session.refresh(track)
                track_id = track.id
            url = f"/api/tracks/{track_id}/performance-metadata"
            initial = client.get(url)
            assert initial.status_code == 200, initial.text
            analyzed = client.post(f"/api/tracks/{track_id}/grid-analysis", json={"force": True})
            assert analyzed.status_code == 200, analyzed.text
            grid = analyzed.json()
            assert grid["source"] == "analysis"
            # Shift all source beats consistently, then change BPM around a
            # selected anchor. Dense variable grids retain their exact ordering.
            grid["first_beat_ms"] += 10
            if grid["beat_times_ms"]:
                grid["beat_times_ms"] = [value + 10 for value in grid["beat_times_ms"]]
                anchor = grid["beat_times_ms"][min(10, len(grid["beat_times_ms"]) - 1)]
                ratio = grid["bpm"] / (grid["bpm"] + .01)
                grid["beat_times_ms"] = [anchor + (value - anchor) * ratio for value in grid["beat_times_ms"]]
                grid["first_beat_ms"] = grid["beat_times_ms"][0]
            grid["bpm"] += .01
            grid["source"] = "manual"
            payload = {"revision": initial.json()["revision"], "beat_grid": grid,
                       "cue_points": [{"slot": 0, "position_ms": 5000, "label": "probe"}],
                       "loops": [{"id": "probe", "start_ms": 10000, "end_ms": 14000}]}
            saved = client.put(url, json=payload)
            assert saved.status_code == 200, saved.text
            assert client.get(url).json() == saved.json()
            assert client.put(url, json=payload).status_code == 409
            for invalid in ({"beat_times_ms": [100, 100], "first_beat_ms": 100},
                            {"first_beat_ms": duration * 1000},
                            {"beat_times_ms": [100, duration * 1000 + 1], "first_beat_ms": 100},
                            {"bpm": 0}):
                rejected = client.put(url, json={**payload, "revision": saved.json()["revision"], "beat_grid": {**grid, **invalid}})
                assert rejected.status_code == 422, rejected.text
                assert client.get(url).json() == saved.json(), "Invalid grid changed saved state"
            # Real legacy decoder is still required by the old-host fallback.
            waveform = client.get(f"/api/play/tracks/{track_id}/waveform-detail?bins=2000")
            assert waveform.status_code == 200, waveform.text
            assert len(waveform.json()["peaks"]) > 0
            assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
            audio = next(stream for stream in info["streams"] if stream["codec_type"] == "audio")
            bundle.append({"id": track_id, "path": str(copy), "sha256": digest, "durationMs": duration * 1000,
                           "codec": audio["codec_name"], "sampleRate": audio["sample_rate"], "metadata": saved.json()})
            print(json.dumps({"track": index, "codec": audio["codec_name"], "gridBpm": grid["bpm"],
                              "beats": len(grid["beat_times_ms"] or []), "api": "passed"}), flush=True)
    (directory / "bundle.json").write_text(json.dumps(bundle))
    print(json.dumps({"bundle": str(directory / "bundle.json"), "passed": len(bundle)}), flush=True)

    @app.get("/validation/bundle")
    def get_bundle():
        return bundle

    if args.serve:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=args.serve)


if __name__ == "__main__":
    main()
