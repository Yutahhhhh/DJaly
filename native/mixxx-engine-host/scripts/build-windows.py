"""Build the pinned real Mixxx host from an MSVC developer command prompt."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / "build-deps"
MIXXX = "3ebac449e7e5fe2a0186596657696e87ce8b0e56"
VCPKG = "3d33b7f7a8121da6e4fa80b35618fc8e960be686"
LDC = "20bf658a60881854984f8ffb1586a4722bf590ec"


def run(*args, cwd=None):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def fetch(url, revision, destination):
    if not (destination / ".git").exists():
        run("git", "init", destination)
        run("git", "-C", destination, "remote", "add", "origin", url)
        run("git", "-C", destination, "fetch", "--depth", "1", "origin", revision)
        run("git", "-C", destination, "checkout", "--detach", "FETCH_HEAD")
    actual = subprocess.check_output(["git", "-C", str(destination), "rev-parse", "HEAD"], text=True).strip()
    if actual != revision:
        raise RuntimeError(f"Unexpected dependency revision: {destination}")


def download(url, destination, digest=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".download")
        run("curl.exe", "--fail", "--location", "--retry", "3", "--connect-timeout", "30", "--max-time", "1800", "--speed-time", "120", "--speed-limit", "1024", "--output", temporary, url)
        temporary.replace(destination)
    if digest and hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f"Checksum mismatch: {destination}")


def configure(source, build, *options):
    run("cmake", "-S", source, "-B", build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_POLICY_VERSION_MINIMUM=3.5", "-DCMAKE_CXX_FLAGS=/utf-8 /DNOMINMAX", *options)


def build(directory, *targets):
    run("cmake", "--build", directory, "--parallel", os.environ.get("PLUMDECK_BUILD_JOBS", "4"),
        *(["--target", *targets] if targets else []))


def main():
    if sys.platform != "win32":
        raise SystemExit("Run from an x64 MSVC developer command prompt on Windows")
    DEPS.mkdir(parents=True, exist_ok=True)
    upstream = ROOT / "upstream"
    fetch("https://github.com/mixxxdj/mixxx.git", MIXXX, upstream)
    # Use the hash-verified dependencies from this exact Mixxx revision.
    name = "mixxx-deps-2.5-x64-windows-release-40c29ff"
    archive = DEPS / f"{name}.zip"
    prefix_root = DEPS / name
    if not prefix_root.exists():
        download(f"https://downloads.mixxx.org/dependencies/2.5-rel/Windows/{name}.zip", archive,
                 "a9d809ae9c52d8a553af1bb8a58565649ced7b1f938d1d37c1c7d83ad53aacf3")
        with zipfile.ZipFile(archive) as source:
            source.extractall(DEPS)
    prefix = prefix_root / "installed" / "x64-windows-release"
    if not prefix.is_dir():
        raise RuntimeError("Mixxx dependency archive has an unexpected layout")
    vcpkg = DEPS / "vcpkg-junction"
    fetch("https://github.com/microsoft/vcpkg.git", VCPKG, vcpkg)
    if not (vcpkg / "vcpkg.exe").exists():
        run("cmd", "/c", vcpkg / "bootstrap-vcpkg.bat", "-disableMetrics")
    triplets = DEPS / "triplets"
    triplets.mkdir(exist_ok=True)
    (triplets / "x64-windows-release.cmake").write_text(
        "set(VCPKG_TARGET_ARCHITECTURE x64)\nset(VCPKG_CRT_LINKAGE dynamic)\n"
        "set(VCPKG_LIBRARY_LINKAGE dynamic)\nset(VCPKG_BUILD_TYPE release)\n")
    run(vcpkg / "vcpkg.exe", "install", "libnice:x64-windows-release", "opus:x64-windows-release",
        "--host-triplet=x64-windows-release", f"--overlay-triplets={triplets}", "--clean-after-build")
    extra = vcpkg / "installed" / "x64-windows-release"
    prefixes = f"{prefix.as_posix()};{extra.as_posix()}"
    ldc = DEPS / "libdatachannel"
    fetch("https://github.com/paullouisageneau/libdatachannel.git", LDC, ldc)
    run("git", "-C", ldc, "submodule", "update", "--init", "--recursive", "--depth", "1")
    pkg = next(iter((vcpkg / "downloads" / "tools").glob("pkgconf*/pkgconf.exe")), None)
    if pkg is None:
        pkg = shutil.which("pkg-config")
    if not pkg:
        raise RuntimeError("vcpkg's pkgconf executable was not found")
    os.environ["PKG_CONFIG_PATH"] = str(extra / "lib" / "pkgconfig")
    configure(ldc, ldc / "build-windows", f"-DCMAKE_PREFIX_PATH={prefixes}", f"-DPKG_CONFIG_EXECUTABLE={pkg}",
        f"-DCMAKE_INSTALL_PREFIX={(ldc / 'install').as_posix()}", "-DBUILD_SHARED_LIBS=ON", "-DUSE_NICE=ON",
        "-DNO_MEDIA=OFF", "-DNO_WEBSOCKET=OFF", "-DNO_EXAMPLES=ON", "-DNO_TESTS=ON")
    build(ldc / "build-windows")
    run("cmake", "--install", ldc / "build-windows")
    for name, url, filename in [
        ("soundtouch", "https://codeberg.org/soundtouch/soundtouch/archive/2.4.1.tar.gz", "source.tar.gz"),
        ("rubberband", "https://breakfastquay.com/files/releases/rubberband-4.0.0.tar.bz2", "source.tar.bz2"),
        ("rubberband", "https://github.com/libsndfile/libsamplerate/releases/download/0.2.2/libsamplerate-0.2.2.tar.xz", "samplerate.tar.xz"),
    ]:
        download(url, DEPS / name / filename)
    # These preparation scripts check the source archive hashes before extraction.
    run(sys.executable, ROOT / "scripts/prepare-soundtouch-checkpoint.py", DEPS / "soundtouch")
    st = DEPS / "soundtouch"
    configure(st / "source", st / "build", "-DBUILD_SHARED_LIBS=OFF", "-DSOUNDSTRETCH=OFF", "-DSOUNDTOUCH_DLL=OFF", "-DOPENMP=OFF", "-DNEON=OFF")
    build(st / "build")
    rb = DEPS / "rubberband"
    run(sys.executable, ROOT / "scripts/prepare-rubberband-checkpoint.py", rb, ROOT / "src/junction")
    (rb / "build-config").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "cmake/rubberband-source.cmake", rb / "build-config/CMakeLists.txt")
    configure(rb / "build-config", rb / "build", f"-DCMAKE_PREFIX_PATH={prefixes}",
        f"-DRB_SOURCE={(rb / 'source').as_posix()}", f"-DRB_PRIVATE={(rb / 'private').as_posix()}", f"-DRB_ADAPTER={(ROOT / 'src/junction').as_posix()}")
    build(rb / "build")
    patch = ROOT / "patches/recording-frame-clock.patch"
    applied = subprocess.run(["git", "-C", str(upstream), "apply", "--reverse", "--check", str(patch)], capture_output=True).returncode == 0
    if not applied:
        run("git", "-C", upstream, "apply", "--check", patch)
        run("git", "-C", upstream, "apply", patch)
    all_prefixes = f"{prefixes};{(ldc / 'install').as_posix()}"
    options = [f"-DCMAKE_PREFIX_PATH={all_prefixes}", f"-DMIXXX_VCPKG_ROOT={prefix_root.as_posix()}",
        "-DVCPKG_TARGET_TRIPLET=x64-windows-release", "-DQML=OFF", "-DBUILD_TESTING=OFF", "-DBUILD_BENCH=OFF",
        "-DENGINEPRIME=OFF", "-DKEYFINDER=OFF", "-DPORTMIDI=OFF", "-DBROADCAST=OFF", "-DQTKEYCHAIN=OFF",
        "-DHID=OFF", "-DBULK=OFF", "-DVINYLCONTROL=OFF", "-DFFMPEG=OFF", "-DBATTERY=OFF", "-DLILV=OFF",
        "-DOPTIMIZE=portable", "-DWARNINGS_FATAL=OFF",
        f"-DCMAKE_PROJECT_mixxx_INCLUDE={(ROOT / 'cmake/inject-host.cmake').as_posix()}"]
    configure(upstream, ROOT / "build-upstream", *options)
    build(ROOT / "build-upstream", "plumdeck-mixxx-engine-host")
    configure(ROOT, ROOT / "build-seam", f"-DCMAKE_PREFIX_PATH={all_prefixes}")
    build(ROOT / "build-seam")
    # Stage a complete relocatable directory. Copy all runtime DLLs from the
    # pinned prefixes; no PATH entry on the end user's machine is needed.
    stage = ROOT / "stage" / "PlumdeckMixxxHost"
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "build-upstream/plumdeck-mixxx-engine-host.exe", stage)
    for location in (prefix / "bin", extra / "bin", ldc / "install/bin"):
        for dll in location.glob("*.dll"):
            shutil.copy2(dll, stage)
    deploy = next(prefix.rglob("windeployqt.exe"))
    run(deploy, "--release", "--no-translations", "--compiler-runtime", stage / "plumdeck-mixxx-engine-host.exe")
    offscreen = next(prefix.rglob("qoffscreen.dll"))
    (stage / "platforms").mkdir(exist_ok=True)
    shutil.copy2(offscreen, stage / "platforms/qoffscreen.dll")
    shutil.copytree(upstream / "res", stage / "res", dirs_exist_ok=True)
    shutil.copytree(extra / "share", stage / "licenses/junction", dirs_exist_ok=True)
    shutil.copytree(prefix / "share", stage / "licenses/mixxx-dependencies", dirs_exist_ok=True)
    shutil.copy2(upstream / "LICENSE", stage / "LICENSE-Mixxx")
    os.environ["PATH"] = str(stage) + os.pathsep + os.environ["PATH"]
    run("ctest", "--test-dir", ROOT / "build-seam", "--output-on-failure")
    run("node", ROOT / "scripts/smoke-bundle.mjs", stage / "plumdeck-mixxx-engine-host.exe")


if __name__ == "__main__":
    main()
