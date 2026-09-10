"""Install this build in a relocated directory and exercise the installed desktop app."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time

SYSTEM32 = Path(os.environ["SystemRoot"]) / "System32"
MSIEXEC = SYSTEM32 / "msiexec.exe"
POWERSHELL = SYSTEM32 / "WindowsPowerShell/v1.0/powershell.exe"


def dump_installer_state(log):
    """Best-effort snapshot when an msiexec call refuses to return."""
    try:
        subprocess.run([str(SYSTEM32 / "tasklist.exe"), "/v", "/fi", "imagename eq msiexec.exe"], timeout=30)
    except Exception as error:  # noqa: BLE001 - diagnostics only
        print(f"tasklist failed: {error}", file=sys.stderr)
    script = (
        f"if (Test-Path -LiteralPath '{log}') {{ Get-Content -LiteralPath '{log}' -Tail 250 }} "
        "else { 'no install.log was created' }; "
        "Get-WinEvent -FilterHashtable @{LogName='Application';ProviderName='MsiInstaller';"
        "StartTime=(Get-Date).AddMinutes(-30)} -ErrorAction SilentlyContinue | "
        "Select-Object -First 30 TimeCreated,Id,LevelDisplayName,Message | Format-List"
    )
    try:
        subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script], timeout=90)
    except Exception as error:  # noqa: BLE001 - diagnostics only
        print(f"state dump failed: {error}", file=sys.stderr)


def run_msi(command, timeout, log=None):
    """Run a pre-quoted msiexec command line and force-kill its tree on overrun.

    The command is passed as a single string so msiexec receives exactly the
    quoting we intend: property values such as INSTALLDIR="C:\\dir with spaces"
    must keep the quotes *around the value*, which a subprocess argument list
    cannot express (it quotes the whole "INSTALLDIR=..." token instead, and
    msiexec then splits the value on the first space).
    """
    process = subprocess.Popen(command)
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if log is not None:
            dump_installer_state(log)
        subprocess.run([str(SYSTEM32 / "taskkill.exe"), "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        raise
    finally:
        if process.poll() is None:
            process.kill()


def main():
    repository = Path(__file__).resolve().parents[1]
    installer = next((repository / "src-tauri/target/release/bundle/msi").glob("*.msi")).resolve()
    with tempfile.TemporaryDirectory(prefix="Plumdeck インストール ") as temporary:
        directory = Path(temporary) / "Application files"
        log = Path(temporary) / "install.log"
        install = (f'"{MSIEXEC}" /i "{installer}" /qn /norestart '
                   f'INSTALLDIR="{directory}" /l*v "{log}"')
        uninstall = f'"{MSIEXEC}" /x "{installer}" /qn /norestart'
        try:
            started = time.monotonic()
            returncode = run_msi(install, timeout=600, log=log)
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
                run_msi(uninstall, timeout=300)
            except (subprocess.TimeoutExpired, OSError) as error:
                print(f"Cleanup uninstall did not complete: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()
