"""Exercise the actual packaged API and MCP server in an isolated user profile."""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


def main():
    executable = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix="Plumdeck 配布 ") as directory:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 48123 if "--desktop" in sys.argv[2:] else 0))
            port = reservation.getsockname()[1]
        env = {**os.environ, "USER_DATA_DIR": directory, "DB_PATH": str(Path(directory) / "library.duckdb"),
               "PLUMDECK_PORT": str(port), "ENV": "prod"}
        if sys.platform == "win32":
            env["PATH"] = os.pathsep.join([str(Path(env["SystemRoot"]) / "System32"), env["SystemRoot"]])
        with tempfile.TemporaryFile() as log:
            child = subprocess.Popen([executable], env=env, stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise RuntimeError(f"Backend exited: {child.returncode}")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
                            assert b"plumdeck Backend API is running" in response.read(4096)
                        break
                    except OSError:
                        time.sleep(.5)
                else:
                    raise TimeoutError("Packaged backend did not become ready")
                payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "distribution-smoke", "version": "1"}}}
                request = Request(f"http://127.0.0.1:{port}/mcp", data=json.dumps(payload).encode(), headers={
                    "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
                with urlopen(request, timeout=15) as response:
                    body = response.read(65536).decode()
                    messages = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")] if body.startswith("event:") else [json.loads(body)]
                    assert any(item.get("result", {}).get("serverInfo") for item in messages), body
                print("Packaged API and MCP initialization passed")
            except Exception:
                log.seek(0)
                print(log.read()[-20000:].decode(errors="replace"), file=sys.stderr)
                raise
            finally:
                if sys.platform == "win32" and child.poll() is None:
                    subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"),
                        "/PID", str(child.pid), "/T", "/F"], capture_output=True)
                elif child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    main()
