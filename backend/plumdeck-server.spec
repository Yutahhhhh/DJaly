# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs
from pathlib import Path
import runpy
import sys

datas = [(
    'models/msd-musicnn-1.onnx' if sys.platform == 'win32' else 'models/msd-musicnn-1.pb',
    'models',
)]
binaries = []

# Package the converter and its linked libraries; installed apps must not rely
# on a developer's Homebrew/Chocolatey installation at runtime.
recording_ffmpeg = runpy.run_path(str(Path(SPECPATH) / 'packaging_ffmpeg.py'))['find_ffmpeg']()
binaries.append((recording_ffmpeg, 'bin'))

hiddenimports = [
    'uvicorn', 'uvicorn.main', 'uvicorn.config', 'uvicorn.logging',
    'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio',
    'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.lifespan', 'uvicorn.lifespan.on', 'uvicorn.lifespan.off',
    'uvicorn.server',
    'starlette', 'starlette.routing', 'starlette.middleware', 'starlette.applications',
    'fastapi', 'fastapi.applications', 'sqlmodel', 'platformdirs', 'pydantic_settings',
    'h11', 'h11._connection', 'h11._state',
    'anyio', 'anyio._backends', 'anyio._backends._asyncio',
    'mcp_server', 'mcp_server.instance', 'mcp_server.server', 'mcp_server.tools',
    'mcp_server.tools.tracks', 'mcp_server.tools.setlists', 'mcp_server.tools.genres',
    'mcp_server.tools.lyrics', 'mcp_server.tools.analysis', 'mcp_server.tools.wordplay',
]

# Collect packages that genuinely use dynamic imports/resources. NumPy is
# handled by PyInstaller's built-in hook. Windows analysis libraries are
# collected separately below because macOS uses Essentia instead.
for package in [
    'uvicorn', 'starlette', 'fastapi', 'h11', 'essentia',
    'mcp', 'mcp_types', 'sse_starlette', 'jsonschema',
]:
    try:
        package_datas, package_binaries, package_imports = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_imports
    except Exception:
        # Some packages are platform-optional (notably Essentia on Windows).
        pass

# Essentia ships native libraries on supported platforms.
if sys.platform != 'win32':
    binaries += collect_dynamic_libs('essentia')
else:
    # Include librosa's lazy-loaded module map and ONNX Runtime's native CPU runtime.
    for package in ['librosa', 'lazy_loader', 'pyloudnorm', 'onnxruntime']:
        package_datas, package_binaries, package_imports = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_imports
    hiddenimports.append('domain.services.analysis.portable')

# Fail the build if Rekordbox-import dependencies are missing; do not silently
# ship a package that relies on another checkout or virtual environment.
for package in ['pyrekordbox', 'sqlcipher3']:
    __import__(package)
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Deduplicate collected resources.
a.binaries = list({(name, path, typecode) for name, path, typecode in a.binaries})
a.datas = list({(name, path, typecode) for name, path, typecode in a.datas})

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='plumdeck-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['*.dylib', '*.so'],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
