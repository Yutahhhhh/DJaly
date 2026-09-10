"""Prepare signed updates after final bundle sealing; combine only complete releases."""
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'src-tauri/tauri.conf.json').read_text())
VERSION = CONFIG['version']


def validate():
    if os.environ.get('GITHUB_REF_NAME') != f'v{VERSION}':
        raise RuntimeError('Release tag must match the version in tauri.conf.json')
    if not os.environ.get('TAURI_SIGNING_PRIVATE_KEY'):
        raise RuntimeError('Configure TAURI_SIGNING_PRIVATE_KEY before publishing updates')


def sign(path):
    env = {**os.environ, 'TAURI_PRIVATE_KEY': os.environ['TAURI_SIGNING_PRIVATE_KEY'],
        'TAURI_PRIVATE_KEY_PASSWORD': os.environ.get('TAURI_SIGNING_PRIVATE_KEY_PASSWORD', '')}
    subprocess.run(['node', str(ROOT / 'node_modules/@tauri-apps/cli/tauri.js'),
        'signer', 'sign', str(path)], env=env, check=True, capture_output=True)
    signature = Path(str(path) + '.sig').read_text().strip()
    public = base64.b64decode(CONFIG['plugins']['updater']['pubkey']).decode().splitlines()[1]
    signed = base64.b64decode(signature).decode().splitlines()[1]
    if base64.b64decode(public)[2:10] != base64.b64decode(signed)[2:10]:
        raise RuntimeError('Signing key does not match the public key embedded in the app')
    return signature


def prepare(platform, output):
    validate()
    output.mkdir(parents=True, exist_ok=True)
    if platform == 'darwin-aarch64':
        bundle = ROOT / 'src-tauri/target/aarch64-apple-darwin/release/bundle'
        app = bundle / 'macos/plumdeck.app'
        assert app.is_dir(), app
        update = output / f'plumdeck_{VERSION}_aarch64.app.tar.gz'
        with tarfile.open(update, 'w:gz', dereference=False) as archive:
            archive.add(app, arcname=app.name)
        files = list((bundle / 'dmg').glob('*.dmg'))
        assert files, 'DMG missing'
    elif platform == 'windows-x86_64':
        bundle = ROOT / 'src-tauri/target/release/bundle'
        nsis = list((bundle / 'nsis').glob('*.exe'))
        msi = list((bundle / 'msi').glob('*.msi'))
        assert len(nsis) == 1 and len(msi) == 1, 'Windows installers missing or ambiguous'
        files = nsis + msi
        update = output / nsis[0].name
    else:
        raise ValueError(platform)
    for file in files:
        shutil.copy2(file, output / file.name)
    signature = sign(update)
    # MSI downloads are signed too, even though automatic updates use NSIS.
    if platform == 'windows-x86_64':
        sign(output / msi[0].name)
    repository = os.environ['GITHUB_REPOSITORY']
    base = os.environ.get('PLUMDECK_RELEASE_DOWNLOAD_BASE', '').rstrip('/') or f'https://github.com/{repository}/releases/download'
    part = {'version': VERSION, 'platform': platform, 'signature': signature,
        'url': f'{base}/v{VERSION}/{quote(update.name)}'}
    (output / f'update-{platform}.json').write_text(json.dumps(part, indent=2) + '\n')


def combine(directory):
    parts = [json.loads(p.read_text()) for p in directory.glob('update-*.json')]
    assert len(parts) == 2 and {p['platform'] for p in parts} == {'darwin-aarch64', 'windows-x86_64'}
    assert all(p['version'] == VERSION and p['signature'] and p['url'].startswith('https://') for p in parts)
    manifest = {'version': VERSION, 'notes': f'plumdeck {VERSION}',
        'pub_date': datetime.now(timezone.utc).isoformat(),
        'platforms': {p['platform']: {'signature': p['signature'], 'url': p['url']} for p in parts}}
    (directory / 'latest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for path in directory.glob('update-*.json'):
        path.unlink()


if __name__ == '__main__':
    if sys.argv[1] == 'validate':
        validate()
    elif sys.argv[1] == 'combine':
        combine(Path(sys.argv[2]))
    else:
        prepare(sys.argv[1], Path(sys.argv[2]))
