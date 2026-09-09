"""Select a converter matching the Python sidecar architecture at build time."""
import platform
from pathlib import Path
import shutil
import subprocess


def find_ffmpeg() -> str:
    candidates = [shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    for candidate in dict.fromkeys(candidates):
        if not candidate or not Path(candidate).is_file():
            continue
        if platform.system() == "Darwin":
            # PyInstaller skips dependency rewriting for foreign-architecture
            # executables. That would silently retain Homebrew library paths.
            result = subprocess.run(["/usr/bin/lipo", candidate, "-verify_arch", platform.machine()], capture_output=True)
            if result.returncode != 0:
                continue
        probe = subprocess.run([candidate, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10)
        if probe.returncode == 0 and {"pcm_s16le", "flac", "libmp3lame"} <= set(probe.stdout.split()):
            return str(Path(candidate).resolve())
    raise RuntimeError(f"FFmpeg with WAV/FLAC/MP3 encoders for {platform.machine()} is required to package recordings")


if __name__ == "__main__":
    print(find_ffmpeg())
