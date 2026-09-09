"""Fresh interpreters avoid the suite's eager Essentia mocking fixture."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap


BACKEND = Path(__file__).resolve().parents[1]


def _isolated(code, tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=BACKEND,
        env={**os.environ, "USER_DATA_DIR": str(tmp_path),
             "DB_PATH": str(tmp_path / "isolated.duckdb")},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_app_import_does_not_load_audio_analyzer(tmp_path):
    _isolated("""
        import importlib.abc
        import sys

        class NoAudioImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if (fullname == 'domain.services.analysis.analyzer'
                        or fullname.split('.')[0] in {'essentia', 'tensorflow'}):
                    raise AssertionError('Eager audio import: ' + fullname)

        sys.meta_path.insert(0, NoAudioImports())
        import ingest
        import main
        assert 'domain.services.analysis.analyzer' not in sys.modules
        assert 'essentia' not in sys.modules
        assert 'tensorflow' not in sys.modules
    """, tmp_path)


def test_lazy_analyzer_preserves_thread_cache_and_wrapper(tmp_path):
    _isolated("""
        import sys
        import threading
        import types
        import ingest

        instances = []
        class FakeAnalyzer:
            def __init__(self):
                instances.append(self)
            def analyze(self, filepath, **kwargs):
                return filepath, kwargs

        fake = types.ModuleType('domain.services.analysis.analyzer')
        fake.AudioAnalyzer = FakeAnalyzer
        sys.modules[fake.__name__] = fake
        first = ingest.get_analyzer()
        assert ingest.get_analyzer() is first
        assert len(instances) == 1
        assert ingest.analyze_track_file('track.wav', skip_basic=True,
            skip_waveform=True, external_lyrics='lyrics') == ('track.wav', {
                'skip_basic': True, 'skip_waveform': True,
                'external_lyrics': 'lyrics'})
        workers = []
        thread = threading.Thread(target=lambda: workers.append(ingest.get_analyzer()))
        thread.start()
        thread.join()
        assert workers[0] is not first
        assert len(instances) == 2
        assert ingest.get_analyzer() is first

        class MissingAnalyzer:
            def __init__(self):
                raise ImportError('unavailable')
        fake.AudioAnalyzer = MissingAnalyzer
        del ingest._thread_local.analyzer
        assert ingest.get_analyzer() is None
        assert ingest.analyze_track_file('track.wav') is None
        fake.AudioAnalyzer = FakeAnalyzer
        assert ingest.get_analyzer() is None  # Preserve cached failure behavior.
    """, tmp_path)
