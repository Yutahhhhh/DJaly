"""Install this build in a relocated directory and exercise the installed desktop app."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def main():
    repository = Path(__file__).resolve().parents[1]
    installer = next((repository / "src-tauri/target/release/bundle/msi").glob("*.msi"))
    msiexec = str(Path(os.environ["SystemRoot"]) / "System32/msiexec.exe")
    with tempfile.TemporaryDirectory(prefix="Plumdeck インストール ") as temporary:
        directory = Path(temporary) / "Application files"
        log = Path(temporary) / "install.log"
        try:
            result = subprocess.run([msiexec, "/i", str(installer), "/qn", "/norestart",
                f"INSTALLDIR={directory}", "/l*vx", str(log)], timeout=180)
            if result.returncode not in (0, 3010):
                raise RuntimeError(f"Installer exited: {result.returncode}")
            app = directory / "plumdeck.exe"
            assert app.is_file(), f"Installed app missing: {directory}"
            assert (directory / "engine/plumdeck-mixxx-engine-host.exe").is_file()
            for _ in range(2):
                subprocess.run([sys.executable, str(repository / "scripts/smoke-backend.py"), str(app), "--desktop"], check=True, timeout=180)
            print("Installed Windows desktop app and MCP passed")
        except Exception:
            if log.exists():
                print(log.read_text(encoding="utf-16", errors="replace")[-16000:], file=sys.stderr)
            raise
        finally:
            subprocess.run([msiexec, "/x", str(installer), "/qn", "/norestart"], timeout=120)


if __name__ == "__main__":
    main()
