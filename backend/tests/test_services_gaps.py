import pytest
import numpy as np
import json
from services.analysis.analyzer import AudioAnalyzer
from services.ingestion_manager import IngestionManager
from sqlmodel import Session
from models import Track

def test_analyzer_loudest_section(mocker):
    # Essentiaがインストールされている前提、または完全にモック
    mocker.patch("essentia.standard.RMS", return_value=lambda x: np.array([0.5]))
    
    # FrameGenerator needs to return enough frames for the logic to work.
    # _extract_loudest_section uses hop_size=sr (1 sec).
    # If we want to test extraction, we need audio longer than duration.
    # Let's say audio is 10 seconds.
    # FrameGenerator will yield approx 10 frames.
    dummy_frames = [np.zeros(2048) for _ in range(10)]
    mocker.patch("essentia.standard.FrameGenerator", return_value=dummy_frames)
    
    analyzer = AudioAnalyzer()
    sr = 44100
    audio = np.random.rand(sr * 10) # 10 seconds
    
    # Extract 2 seconds
    section = analyzer._extract_loudest_section(audio, duration_sec=2)
    
    # Should return exactly 2 seconds worth of samples
    assert len(section) == 2 * sr

def test_analyzer_compute_peaks():
    analyzer = AudioAnalyzer()
    audio = np.array([0.1, -0.2, 0.3, -0.4])
    peaks = analyzer._compute_waveform_peaks(audio, num_points=2)
    assert len(peaks) == 2
    assert peaks == [0.2, 0.4]

@pytest.mark.asyncio
async def test_ingestion_manager_broadcast(mocker):
    manager = IngestionManager()
    mock_ws = mocker.AsyncMock()
    await manager.connect(mock_ws)
    
    # Broadcast progress
    await manager.broadcast({"type": "progress", "current": 1, "total": 10})
    assert mock_ws.send_json.called

def test_genre_expander_cache(session, mocker):
    from utils.genres import GenreExpander
    expander = GenreExpander()
    expander.cache = {"Techno": ["Minimal Techno"]}
    
    # Cache hit
    res = expander.expand(session, "Techno")
    assert "Minimal Techno" in res
    
    # Cache miss + LLM
    mocker.patch("utils.genres.generate_text", return_value='["Deep House"]')
    res = expander.expand(session, "House")
    assert "Deep House" in res
