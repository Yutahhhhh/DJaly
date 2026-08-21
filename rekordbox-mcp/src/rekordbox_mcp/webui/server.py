"""Static HTTP server for the Rekordbox web UI."""

from __future__ import annotations

import argparse
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from rekordbox_mcp.config import get_settings


PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATIC_ROOT = PROJECT_ROOT / "webui" / "dist"


class _StaticRequestHandler(SimpleHTTPRequestHandler):
    """Serve static files, falling back to the SPA entry point for routes."""

    def end_headers(self) -> None:
        """Add headers needed when the UI and Web API use different ports."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        """Handle browser CORS preflight requests."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def translate_path(self, path: str) -> str:
        """Use index.html for client-side routes not backed by a file."""
        translated = Path(super().translate_path(path))
        url_path = urlsplit(path).path

        # A missing URL without a file extension is a React Router route.  Do
        # not turn missing JS/CSS/image requests into an HTML response.
        if url_path not in ("", "/") and not translated.exists() and not Path(url_path).suffix:
            return str(Path(self.directory or ".") / "index.html")
        return str(translated)


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def create_server(host: str, port: int, static_root: Path = STATIC_ROOT) -> ThreadingHTTPServer:
    """Create the web UI server without starting its blocking serve loop."""
    if not static_root.is_dir():
        raise FileNotFoundError(f"Web UI build directory does not exist: {static_root}")

    handler = partial(_StaticRequestHandler, directory=str(static_root))
    return _ReusableThreadingHTTPServer((host, port), handler)


def main() -> None:
    """Run the web UI server."""
    parser = argparse.ArgumentParser(description="Rekordbox Web UI Server")
    parser.add_argument("--host", type=str, help="Web UI host (defaults to config webui_host)")
    parser.add_argument("--port", type=int, help="Web UI port (defaults to config webui_port)")
    parser.add_argument("--version", action="version", version="Rekordbox Web UI Server 1.0.0")
    args = parser.parse_args()

    settings = get_settings()
    host = args.host or settings.webui_host
    port = args.port or settings.webui_port
    server = create_server(host, port)

    print(f"Rekordbox Web UI serving {STATIC_ROOT} at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
