import json
from typing import Any, Dict, List, Optional

from mcp_server.instance import mcp, db_session, serialize, track_list_payload
from app.services.setlist_app_service import SetlistAppService


@mcp.tool()
def list_setlists() -> Dict[str, Any]:
    """全セットリストの一覧を返す。"""
    with db_session() as session:
        service = SetlistAppService(session)
        return {"setlists": serialize(service.get_setlists())}


@mcp.tool()
def create_setlist(name: str) -> Dict[str, Any]:
    """新しい空のセットリストを作成する。"""
    with db_session() as session:
        service = SetlistAppService(session)
        return serialize(service.create_setlist(name))


@mcp.tool()
def rename_setlist(setlist_id: int, name: str) -> Dict[str, Any]:
    """セットリストの名前を変更する。"""
    with db_session() as session:
        service = SetlistAppService(session)
        result = service.update_setlist(setlist_id, {"name": name})
        if not result:
            raise ValueError(f"Setlist {setlist_id} not found")
        return serialize(result)


@mcp.tool()
def delete_setlist(setlist_id: int) -> Dict[str, Any]:
    """セットリストを削除する（曲データも含めて完全に削除）。"""
    with db_session() as session:
        service = SetlistAppService(session)
        ok = service.delete_setlist(setlist_id)
        if not ok:
            raise ValueError(f"Setlist {setlist_id} not found")
        return {"ok": True}

@mcp.tool()
def get_setlist_tracks(setlist_id: int) -> Dict[str, Any]:
    """セットリストに含まれる楽曲を、並び順どおりに返す。"""
    with db_session() as session:
        service = SetlistAppService(session)
        return track_list_payload(service.get_setlist_tracks(setlist_id))


@mcp.tool()
def set_setlist_tracks(setlist_id: int, track_ids: List[int]) -> Dict[str, Any]:
    """セットリストの曲構成を指定した track_id の並び順に一括で置き換える（既存の曲構成は破棄される）。"""
    with db_session() as session:
        service = SetlistAppService(session)
        ok = service.update_setlist_tracks(setlist_id, track_ids)
        if not ok:
            raise ValueError(f"Setlist {setlist_id} not found")
        return track_list_payload(service.get_setlist_tracks(setlist_id))


@mcp.tool()
def add_track_to_setlist(setlist_id: int, track_id: int, position: Optional[int] = None) -> Dict[str, Any]:
    """セットリストに1曲追加する。position を指定しない場合は末尾に追加。"""
    with db_session() as session:
        service = SetlistAppService(session)
        current = service.get_setlist_tracks(setlist_id)
        ids = [t["id"] for t in current]
        if position is None:
            ids.append(track_id)
        else:
            ids.insert(max(0, min(position, len(ids))), track_id)
        service.update_setlist_tracks(setlist_id, ids)
        return track_list_payload(service.get_setlist_tracks(setlist_id))


@mcp.tool()
def remove_track_from_setlist(setlist_id: int, track_id: int) -> Dict[str, Any]:
    """セットリストから指定した楽曲を1件削除する（同じ曲が複数あれば最初の1件のみ）。"""
    with db_session() as session:
        service = SetlistAppService(session)
        current = service.get_setlist_tracks(setlist_id)
        ids = [t["id"] for t in current]
        if track_id in ids:
            ids.remove(track_id)
        service.update_setlist_tracks(setlist_id, ids)
        return track_list_payload(service.get_setlist_tracks(setlist_id))


@mcp.tool()
def recommend_next_track(
    track_id: int,
    limit: int = 10,
    genres: Optional[List[str]] = None,
    subgenres: Optional[List[str]] = None,
    target_bpm: Optional[float] = None,
    target_energy: Optional[float] = None,
    target_danceability: Optional[float] = None,
    target_brightness: Optional[float] = None,
) -> Dict[str, Any]:
    """指定した曲の次に繋ぐのに適した楽曲を、BPM/キー/音響類似度からスコアリングして提案する。
    ユーザーの自然言語の方向性はMCPクライアント側で target_* 値へ解釈する。
    target未指定なら純粋にベクトル/BPM/キーのみで評価する。
    """
    with db_session() as session:
        service = SetlistAppService(session)
        results = service.recommend_next_track(
            track_id,
            limit=limit,
            target_params={
                "bpm": target_bpm,
                "energy": target_energy,
                "danceability": target_danceability,
                "brightness": target_brightness,
            },
            genres=genres,
            subgenres=subgenres,
        )
        return track_list_payload(results)


@mcp.tool()
def generate_auto_setlist(
    length: Optional[int] = None,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    seed_track_ids: Optional[List[int]] = None,
    genres: Optional[List[str]] = None,
    subgenres: Optional[List[str]] = None,
    target_bpm: Optional[float] = None,
    target_energy: Optional[float] = None,
    target_danceability: Optional[float] = None,
    target_brightness: Optional[float] = None,
) -> Dict[str, Any]:
    """構造化された音響特徴量ターゲットに基づき、セットリスト候補を自動生成する
    （DBには保存しない、結果一覧を返すのみ。保存するには set_setlist_tracks を別途呼ぶこと）。
    ユーザーの自然言語のvibeは、このツールを呼ぶMCPクライアント自身が target_* と
    genres/subgenres に解釈する。
    曲数は length で指定、min_length/max_length を渡すとその範囲でランダムに決定する。
    length 未指定時は UI 設定のデフォルト曲数（setlist_default_length）を使用する。
    seed_track_ids を渡すとその曲群の流れを引き継いで生成する。
    """
    with db_session() as session:
        service = SetlistAppService(session)
        results = service.generate_auto_setlist(
            target_params={
                "bpm": target_bpm,
                "energy": target_energy,
                "danceability": target_danceability,
                "brightness": target_brightness,
            },
            limit=length,
            min_length=min_length,
            max_length=max_length,
            seed_track_ids=seed_track_ids,
            genres=genres,
            subgenres=subgenres,
        )
        return track_list_payload(results)


@mcp.tool()
def generate_bridge_setlist(
    start_track_id: int,
    end_track_id: int,
    length: int = 5,
    genres: Optional[List[str]] = None,
    subgenres: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """開始曲と終了曲を指定し、その間を自然に繋ぐ中間曲を自動生成する（結果は保存されない）。length は開始・終了を含む合計曲数。"""
    with db_session() as session:
        service = SetlistAppService(session)
        results = service.generate_path_setlist(
            start_track_id, end_track_id, length, genres=genres, subgenres=subgenres
        )
        return track_list_payload(results)


@mcp.tool()
def export_setlist_m3u8(setlist_id: int) -> Dict[str, Any]:
    """セットリストを M3U8 プレイリスト形式のテキストとしてエクスポートする（Rekordbox等に読み込み可能）。
    移動/削除済みのファイルは '# MISSING:' 行として出力される。呼び出し前に validate_setlist_export での確認を推奨。
    """
    with db_session() as session:
        service = SetlistAppService(session)
        content = service.export_as_m3u8(setlist_id)
        return {"setlist_id": setlist_id, "m3u8": content}


@mcp.tool()
def validate_setlist_export(setlist_id: int) -> Dict[str, Any]:
    """エクスポート前にセットリスト内の楽曲ファイルが実際にディスク上に存在するか検証する。"""
    with db_session() as session:
        service = SetlistAppService(session)
        return serialize(service.validate_export(setlist_id))


@mcp.tool()
def add_track_to_setlist_with_wordplay(
    setlist_id: int,
    track_id: int,
    position: Optional[int] = None,
    keyword: Optional[str] = None,
    source_phrase: Optional[str] = None,
    target_phrase: Optional[str] = None,
    from_timestamp: Optional[float] = None,
    to_timestamp: Optional[float] = None,
) -> Dict[str, Any]:
    """セットリストに1曲をワードプレイ情報（繋ぎのキーワードとフレーズ）付きで追加する。"""
    with db_session() as session:
        service = SetlistAppService(session)
        current = service.get_setlist_tracks(setlist_id)
        # 既存曲のワードプレイ情報を保持したまま受け渡す
        track_data: List[Dict[str, Any]] = [
            {"id": t["id"], "wordplay_json": t.get("wordplay_json")} for t in current
        ]

        wp: Dict[str, Any] = {}
        if keyword is not None:
            wp["keyword"] = keyword
        if source_phrase is not None:
            wp["source_phrase"] = source_phrase
        if target_phrase is not None:
            wp["target_phrase"] = target_phrase
        if from_timestamp is not None:
            wp["from_timestamp"] = from_timestamp
        if to_timestamp is not None:
            wp["to_timestamp"] = to_timestamp

        entry: Dict[str, Any] = {"id": track_id}
        if wp:
            entry["wordplay_json"] = json.dumps(wp, ensure_ascii=False)

        if position is None:
            track_data.append(entry)
        else:
            track_data.insert(max(0, min(position, len(track_data))), entry)

        service.update_setlist_tracks(setlist_id, track_data)
        return track_list_payload(service.get_setlist_tracks(setlist_id))


@mcp.tool()
def update_setlist_track_wordplay(setlist_track_id: int, wordplay: Dict[str, Any]) -> Dict[str, Any]:
    """セットリスト内の曲にワードプレイ情報を設定する。wordplay は {keyword, source_phrase, target_phrase, from_timestamp, to_timestamp} 形式の dict。"""
    from domain.models.setlist import SetlistTrack

    with db_session() as session:
        st = session.get(SetlistTrack, setlist_track_id)
        if not st:
            raise ValueError(f"Setlist track {setlist_track_id} not found")
        st.wordplay_json = json.dumps(wordplay, ensure_ascii=False)
        session.add(st)
        session.commit()
        session.refresh(st)
        return serialize(st)


@mcp.tool()
def clear_setlist_track_wordplay(setlist_track_id: int) -> Dict[str, Any]:
    """セットリスト内の曲のワードプレイ情報をクリアする。"""
    from domain.models.setlist import SetlistTrack

    with db_session() as session:
        st = session.get(SetlistTrack, setlist_track_id)
        if not st:
            raise ValueError(f"Setlist track {setlist_track_id} not found")
        st.wordplay_json = None
        session.add(st)
        session.commit()
        return {"ok": True}
