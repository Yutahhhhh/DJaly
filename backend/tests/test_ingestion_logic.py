import pytest
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock
from domain.services.ingestion_domain_service import IngestionDomainService

@pytest.mark.asyncio
async def test_process_track_ingestion_imports_lrc(tmp_path, mocker):
    # Setup files
    mp3_path = tmp_path / "test_track.mp3"
    lrc_path = tmp_path / "test_track.lrc"
    
    mp3_path.touch()
    lrc_path.write_text("LRC Lyrics Content", encoding="utf-8")
    
    # Mock dependencies
    mocker.patch("domain.services.ingestion_domain_service.Session")
    mocker.patch("domain.services.ingestion_domain_service.db_connection")
    mocker.patch("domain.services.ingestion_domain_service.select")
    
    # Mock update_file_metadata to verify it gets called with LRC content
    mock_update_metadata = mocker.patch("domain.services.ingestion_domain_service.update_file_metadata")
    
    # Mock other calls to avoid errors
    mocker.patch("domain.services.ingestion_domain_service.TinyTag.get")
    mocker.patch("domain.services.ingestion_domain_service.extract_metadata_smart", return_value={
        "title": "Title", "artist": "Artist", "album": "Album", "genre": "Genre"
    })
    mocker.patch("domain.services.ingestion_domain_service.analyze_track_file", return_value={})
    mocker.patch("domain.services.ingestion_domain_service.has_valid_metadata", return_value=True)
    
    service = IngestionDomainService()
    loop = asyncio.get_running_loop()
    
    # Run ingestion
    await service.process_track_ingestion(
        filepath=str(mp3_path),
        force_update=False,
        loop=loop,
        save_to_db=False
    )
    
    # Verify update_file_metadata was called with the lyrics from the file
    mock_update_metadata.assert_called_once_with(str(mp3_path), "LRC Lyrics Content")
