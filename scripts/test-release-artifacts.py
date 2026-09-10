"""Verify release signing and all-platform publication with disposable keys."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('release_artifacts', Path(__file__).with_name('release-artifacts.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_real_signing_and_incomplete_release_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = root / 'disposable.key'
            subprocess.run(['node', str(release.ROOT / 'node_modules/@tauri-apps/cli/tauri.js'),
                'signer', 'generate', '--ci', '-p', 'disposable-test', '-w', str(key)],
                check=True, capture_output=True)
            payload = root / 'installer.exe'
            payload.write_bytes(b'Disposable test payload')
            with patch.dict(os.environ, {'TAURI_SIGNING_PRIVATE_KEY': key.read_text().strip(),
                    'TAURI_SIGNING_PRIVATE_KEY_PASSWORD': 'disposable-test'}):
                with self.assertRaisesRegex(RuntimeError, 'does not match'):
                    release.sign(payload)
                with patch.dict(release.CONFIG['plugins']['updater'], {'pubkey': Path(str(key) + '.pub').read_text().strip()}):
                    signature = release.sign(payload)
            def part(platform):
                (root / f'update-{platform}.json').write_text(json.dumps({'version': release.VERSION,
                    'platform': platform, 'signature': signature, 'url': 'https://example.com/installer.exe'}))
            part('darwin-aarch64')
            with self.assertRaises(AssertionError):
                release.combine(root)
            self.assertFalse((root / 'latest.json').exists())
            part('windows-x86_64')
            release.combine(root)
            self.assertEqual(len(json.loads((root / 'latest.json').read_text())['platforms']), 2)


if __name__ == '__main__':
    unittest.main()
