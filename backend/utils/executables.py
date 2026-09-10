"""Resolve packaged tools before optional developer installations."""
import os
from pathlib import Path
import shutil
import sys


def find_ffmpeg() -> str | None:
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        bundled = Path(bundle_root) / "bin" / name
        if bundled.is_file() and os.access(bundled, os.X_OK):
            return str(bundled)
        # A broken installation must not silently use an unrelated system tool.
        return None
    executable = shutil.which(name)
    if executable:
        return executable
    if sys.platform == "darwin":
        for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
            candidate = Path(prefix) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None
