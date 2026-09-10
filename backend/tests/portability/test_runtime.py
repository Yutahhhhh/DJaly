"""No audio inference or user databases: exercise installation boundaries."""
import sys

import pytest

from utils import executables
from config import Settings


@pytest.mark.parametrize("platform,name", [("darwin", "ffmpeg"), ("win32", "ffmpeg.exe")])
def test_packaged_converter_with_spaces_and_no_path(tmp_path, monkeypatch, platform, name):
    root = tmp_path / "音楽 App"
    binary = root / "bin" / name
    binary.parent.mkdir(parents=True)
    binary.write_text("fixture")
    binary.chmod(0o755)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)
    monkeypatch.setenv("PATH", "")
    assert executables.find_ffmpeg() == str(binary)


def test_missing_packaged_converter_does_not_use_developer_install(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(executables.shutil, "which", lambda _: "/developer/bin/ffmpeg")
    assert executables.find_ffmpeg() is None


def test_development_converter_from_path(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(executables.shutil, "which", lambda _: "/custom/ffmpeg")
    assert executables.find_ffmpeg() == "/custom/ffmpeg"


def test_default_music_folder_uses_platform_directory(monkeypatch):
    monkeypatch.delenv("MUSIC_DIR", raising=False)
    import platformdirs
    assert Settings(_env_file=None).MUSIC_DIR == platformdirs.user_music_dir()


def test_user_data_override_is_preserved(tmp_path):
    settings = Settings(_env_file=None, USER_DATA_DIR=str(tmp_path), DB_PATH=None)
    assert settings.DB_PATH == str(tmp_path / "plumdeck.duckdb")
    assert settings.PLUMDECK_LOG_DIR == str(tmp_path / "logs")


def test_packaging_resolves_chocolatey_launcher(tmp_path, monkeypatch):
    import packaging_ffmpeg
    root = tmp_path / "Chocolatey install"
    shim = root / "bin" / "ffmpeg.exe"
    real = root / "lib" / "ffmpeg" / "tools" / "ffmpeg-version" / "bin" / "ffmpeg.exe"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"actual converter")
    monkeypatch.setenv("ChocolateyInstall", str(root))
    monkeypatch.delenv("PLUMDECK_FFMPEG", raising=False)
    monkeypatch.setattr(packaging_ffmpeg.platform, "system", lambda: "Windows")
    monkeypatch.setattr(packaging_ffmpeg.shutil, "which", lambda _: str(shim))
    candidates = packaging_ffmpeg.build_candidates()
    assert str(real) in candidates
    assert str(shim) not in candidates
