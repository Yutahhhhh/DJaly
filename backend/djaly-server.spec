# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas = [('models/msd-musicnn-1.pb', 'models')]
binaries = []
hiddenimports = ['uvicorn', 'uvicorn.main', 'uvicorn.config', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.http.httptools_impl', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.wsproto_impl', 'uvicorn.protocols.websockets.websockets_impl', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'uvicorn.lifespan.off', 'uvicorn.server', 'starlette', 'starlette.routing', 'starlette.middleware', 'starlette.applications', 'fastapi', 'fastapi.applications', 'sqlmodel', 'platformdirs', 'pydantic_settings', 'sklearn.utils._typedefs', 'sklearn.neighbors._partition_nodes', 'scipy.special.cython_special', 'h11', 'h11._connection', 'h11._state', 'anyio', 'anyio._backends', 'anyio._backends._asyncio']

# 主要な依存関係を収集
for package in ['uvicorn', 'starlette', 'fastapi', 'h11', 'essentia', 'numpy', 'scipy', 'sklearn', 'tensorflow']:
    try:
        tmp_ret = collect_all(package)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except:
        pass

# essentiaの動的ライブラリを明示的に収集
binaries += collect_dynamic_libs('essentia')

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

# 重複を削除
a.binaries = list({(name, path, typecode) for name, path, typecode in a.binaries})
a.datas = list({(name, path, typecode) for name, path, typecode in a.datas})

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='djaly-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['*.dylib', '*.so'],  # 動的ライブラリはUPX圧縮を避ける
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
