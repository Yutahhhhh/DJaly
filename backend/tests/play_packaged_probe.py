"""Check bundled Play APIs against a disposable database, never user data."""
import json
import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


async def check_mcp(base):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    async with streamable_http_client(base + "/mcp") as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert "recommend_next_track_page" in names
            result = await client.call_tool("search_tracks", {"limit": 1, "offset": 0})
            assert not result.is_error
            payload = json.loads(result.content[0].text)
            assert payload["total"] == 0 and payload["tracks"] == []


def main():
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="djaly-play-bundle-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, DB_PATH=str(Path(directory) / "probe.duckdb"),
                   USER_DATA_DIR=directory, DJALY_PORT=str(port), PYTHONUNBUFFERED="1")
        base = f"http://127.0.0.1:{port}"

        def request(path, method="GET", payload=None):
            body = None if payload is None else json.dumps(payload).encode()
            req = urllib.request.Request(base + path, data=body, method=method,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read()
                return json.loads(data) if data else None

        with open(Path(directory) / "server.log", "w+") as log:
            process = subprocess.Popen([str(executable)], env=env, stdout=log, stderr=log)
            try:
                started = time.monotonic()
                deadline = started + 300
                while True:
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read()[-5000:])
                    try:
                        request("/")
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Packaged server startup timed out")
                        time.sleep(0.2)
                page = request("/api/tracks/page?limit=10&offset=0")
                assert page["total"] == 0 and page["items"] == [] and not page["has_more"]
                created = request("/api/play/playlists", "POST", {"name": "Bundle probe"})
                playlist_id = created["id"]
                request(f"/api/play/playlists/{playlist_id}", "PATCH", {"name": "Renamed probe"})
                playlists = request("/api/play/playlists?limit=10&offset=0")
                assert playlists["total"] == 1 and playlists["items"][0]["name"] == "Renamed probe"
                tracks = request(f"/api/play/playlists/{playlist_id}/tracks?limit=10&offset=0")
                assert tracks["total"] == 0
                request(f"/api/play/playlists/{playlist_id}", "DELETE")
                assert request("/api/play/playlists?limit=10&offset=0")["total"] == 0
                asyncio.run(asyncio.wait_for(check_mcp(base), timeout=30))
                print(json.dumps({"passed": True, "isolated_database": True, "checks": 8,
                                  "elapsed_seconds": round(time.monotonic() - started, 2)}))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
