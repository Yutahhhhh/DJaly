"""Install this build in a relocated directory and exercise the installed desktop app."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time


def run_tree(command, timeout):
    """Run a command and forcibly terminate its whole process tree if it overruns."""
    process = subprocess.Popen(command)
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"),
            "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        raise
    finally:
        if process.poll() is None:
            process.kill()


def main():
    repository = Path(__file__).resolve().parents[1]
    installer = next((repository / "src-tauri/target/release/bundle/msi").glob("*.msi"))
    msiexec = str(Path(os.environ["SystemRoot"]) / "System32/msiexec.exe")
    with tempfile.TemporaryDirectory(prefix="Plumdeck インストール ") as temporary:
        directory = Path(temporary) / "Application files"
        log = Path(temporary) / "install.log"
        try:
            started = time.monotonic()
            # The bundled backend and engine payload is ~700 MB, so a silent install
            # legitimately runs for several minutes on a CI runner; keep the ceiling
            # bounded but generous and avoid the extra-debug "x" log flag that stalls
            # large installs by flushing after every file operation.
            returncode = run_tree([msiexec, "/i", str(installer), "/qn", "/norestart",
                f"INSTALLDIR={directory}", "/l*v", str(log)], timeout=900)
            print(f"Installer finished in {time.monotonic() - started:.0f}s with code {returncode}")
            if returncode not in (0, 3010):
                raise RuntimeError(f"Installer exited: {returncode}")
            app = directory / "plumdeck.exe"
            assert app.is_file(), f"Installed app missing: {directory}"
            assert (directory / "engine/plumdeck-mixxx-engine-host.exe").is_file()
            for _ in range(2):
                subprocess.run([sys.executable, str(repository / "scripts/smoke-backend.py"), str(app), "--desktop"], check=True, timeout=240)
            print("Installed Windows desktop app and MCP passed")
        except Exception:
            if log.exists():
                try:
                    text = log.read_text(encoding="utf-16", errors="replace")
                except (OSError, UnicodeError):
                    text = log.read_text(encoding="utf-8", errors="replace")
                print(text[-16000:], file=sys.stderr)
            raise
        finally:
            try:
                run_tree([msiexec, "/x", str(installer), "/qn", "/norestart"], timeout=300)
            except (subprocess.TimeoutExpired, OSError) as error:
                print(f"Cleanup uninstall did not complete: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()
