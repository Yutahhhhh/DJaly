"""Select a converter matching the Python sidecar architecture at build time."""
import os
import platform
from pathlib import Path
import shutil
import subprocess


def build_candidates() -> list[str]:
    candidates = []
    explicit = os.environ.get("PLUMDECK_FFMPEG")
    if explicit:
        candidates.append(explicit)
    selected = shutil.which("ffmpeg")
    if platform.system() == "Windows":
        # Chocolatey's bin/ffmpeg.exe is a launcher with an installation-specific
        # target. Bundle the actual executable from the package, never the shim.
        chocolatey = Path(os.environ.get("ChocolateyInstall", r"C:\ProgramData\chocolatey"))
        candidates.extend(str(p) for p in sorted((chocolatey / "lib").glob("ffmpeg*/tools/**/ffmpeg.exe")))
        if selected:
            path = Path(selected)
            scoop = path.with_suffix(".shim")
            if scoop.is_file():
                for line in scoop.read_text(encoding="utf-8-sig").splitlines():
                    if line.startswith("path = "):
                        candidates.append(line[7:].strip().strip('"'))
            elif path.parent.resolve() != (chocolatey / "bin").resolve():
                candidates.append(selected)
    else:
        candidates.extend([selected, "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"])
    return [str(p) for p in candidates if p]


def find_ffmpeg() -> str:
    candidates = build_candidates()
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
