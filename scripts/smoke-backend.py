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


def close_desktop(pid):
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    sent = []
    @callback_type
    def visit(window, context):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == pid:
            sent.append(bool(user.PostMessageW(window, 0x10, 0, 0)))  # WM_CLOSE
        return True
    user.EnumWindows(visit, 0)
    assert any(sent), "Desktop window not found for normal close"


def main():
    executable = str(Path(sys.argv[1]).resolve())
    desktop = "--desktop" in sys.argv[2:]
    with tempfile.TemporaryDirectory(prefix="Plumdeck 配布 ") as directory:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 48123 if desktop else 0))
            port = reservation.getsockname()[1]
        env = {**os.environ, "USER_DATA_DIR": directory, "DB_PATH": str(Path(directory) / "library.duckdb"),
               "PLUMDECK_PORT": str(port), "ENV": "prod", "PLUMDECK_MANAGED_SIDECAR": "1"}
        if sys.platform == "win32":
            system_root = os.environ["SystemRoot"]
            env["PATH"] = os.pathsep.join([str(Path(system_root) / "System32"), system_root])
        with tempfile.TemporaryFile() as log:
            child = subprocess.Popen([executable], env=env, stdin=subprocess.PIPE, stdout=log, stderr=log,
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
                headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
                def rpc(payload):
                    request = Request(f"http://127.0.0.1:{port}/mcp", data=json.dumps(payload).encode(), headers=headers)
                    with urlopen(request, timeout=15) as response:
                        if response.headers.get("Mcp-Session-Id"):
                            headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
                        body = response.read(2*1024*1024+1).decode()
                        assert len(body) <= 2*1024*1024
                        if not body.strip():
                            return None
                        events = [json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith("data:")]
                        messages = events or [json.loads(body)]
                        result = next(item for item in messages if item.get("id") == payload.get("id"))
                        assert "error" not in result, result
                        return result["result"]
                initialized = rpc(payload)
                assert initialized.get("serverInfo"), initialized
                headers["MCP-Protocol-Version"] = initialized["protocolVersion"]
                rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
                listed = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                assert any(tool["name"] == "search_tracks" for tool in listed["tools"])
                searched = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                    "name": "search_tracks", "arguments": {"limit": 1}}})
                assert not searched.get("isError"), searched
                data = searched.get("structuredContent") or json.loads(next(item["text"] for item in searched["content"] if item["type"] == "text"))
                data = data.get("result", data)  # MCP wraps generic dictionary return annotations.
                assert data.get("count") == 0 and data.get("tracks") == [], data
                print("Packaged API, MCP initialization, tool discovery and library search passed")
                if desktop:
                    close_desktop(child.pid)
                else:
                    child.stdin.write(b"plumdeck:shutdown\n")
                    child.stdin.flush()
                    child.stdin.close()
                assert child.wait(timeout=25) == 0, "Normal shutdown failed"
                with socket.socket() as probe:
                    probe.settimeout(1)
                    assert probe.connect_ex(("127.0.0.1", port)) != 0, "Backend listener survived app shutdown"
                print("Normal shutdown released the API/MCP port")
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
