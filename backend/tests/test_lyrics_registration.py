import pytest
from sqlmodel import Session
from models import Lyrics
from tests.test_mcp_server import mcp_session, _add_track, _result_dict


@pytest.mark.asyncio
async def test_register_roundtrip_preserve_and_overwrite(mcp_session, session: Session):
    track = _add_track(session, "/registration.mp3", "Registration")
    content = "[00:01.00]自作テストの歌詞\n[00:03.00]次の行"
    args = dict(track_id=track.id, content=content, source="local:lrc", language="ja")
    result = await mcp_session.call_tool("register_track_lyrics", args)
    assert _result_dict(result)["status"] == "created"
    data = _result_dict(await mcp_session.call_tool("get_track_lyrics", {"track_id": track.id}))
    assert data["content"] == content
    assert data["source"] == "local:lrc"
    assert data["language"] == "ja"
    session.rollback()
    existing = session.get(Lyrics, track.id)
    existing.keywords_json = '["cached"]'
    existing.keywords_content_hash = "old"
    session.add(existing)
    session.commit()
    args["content"] = "Replacement test text"
    assert _result_dict(await mcp_session.call_tool("register_track_lyrics", args))["status"] == "skipped_existing"
    args["overwrite"] = True
    assert _result_dict(await mcp_session.call_tool("register_track_lyrics", args))["status"] == "updated"
    session.rollback()
    session.expire_all()
    assert session.get(Lyrics, track.id).keywords_json is None
    assert session.get(Lyrics, track.id).keywords_content_hash is None
    assert _result_dict(await mcp_session.call_tool("register_track_lyrics", args))["status"] == "unchanged"


@pytest.mark.asyncio
async def test_batch_validation_and_atomicity(mcp_session, session: Session):
    t1 = _add_track(session, "/batch1.mp3", "Batch1")
    t2 = _add_track(session, "/batch2.mp3", "Batch2")
    first = {"track_id": t1.id, "content": "Test content"}
    for items in ([], [first, first], [first, {"track_id": 999999, "content": "Missing"}],
                  [first, {"track_id": t2.id, "content": "  "}], [first] * 101):
        result = await mcp_session.call_tool("register_track_lyrics_batch", {"items": items})
        assert result.is_error
        session.expire_all()
        assert session.get(Lyrics, t1.id) is None
    result = await mcp_session.call_tool("register_track_lyrics_batch", {
        "items": [first, {"track_id": t2.id, "content": "Second test"}]})
    assert [r["status"] for r in _result_dict(result)["results"]] == ["created", "created"]
    result = await mcp_session.call_tool("search_lyrics", {"q": "Second test"})
    assert _result_dict(result)["results"][0]["track"]["id"] == t2.id
