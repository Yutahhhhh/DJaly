import os
import base64
from typing import Dict, Optional, Any
from tinytag import TinyTag
import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, USLT, APIC
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture

def has_valid_metadata(track: Any) -> bool:
    """
    トラックのメタデータが実用的（Unknownではない）かどうかを判定する。
    ingestion.py からインポートされるため、ここで定義。
    """
    if not track:
        return False
    
    # ArtistやTitleが None, 空文字, または "Unknown" の場合は不完全とみなす
    artist = getattr(track, "artist", "Unknown")
    title = getattr(track, "title", "Unknown")
    
    if not artist or str(artist).lower() == "unknown":
        return False
    if not title or str(title).lower() == "unknown":
        return False
        
    return True

def extract_full_metadata(filepath: str) -> Dict[str, Any]:
    """TinyTagとMutagenを併用して詳細なメタデータを取得する"""
    try:
        tag = TinyTag.get(filepath, image=True)
        artwork_base64 = None
        image_data = tag.get_image()
        if image_data:
            artwork_base64 = base64.b64encode(image_data).decode('utf-8')
            
        return {
            "title": tag.title,
            "artist": tag.artist,
            "album": tag.album,
            "lyrics": tag.extra.get('lyrics', ''),
            "artwork": artwork_base64
        }
    except Exception as e:
        print(f"Error reading metadata for {filepath}: {e}")
        return {"title": None, "artist": None, "album": None, "lyrics": "", "artwork": None}

def extract_metadata_smart(filepath: str, tag: Optional[TinyTag] = None) -> Dict[str, str]:
    """
    ファイル名等からメタデータを補完する。
    """
    if tag is None:
        try:
            tag = TinyTag.get(filepath)
        except:
            tag = TinyTag(None, 0)

    filename_fallback = os.path.splitext(os.path.basename(filepath))[0]

    year = None
    if tag.year:
        try:
            year = int(str(tag.year).strip()[:4])
        except:
            pass

    res = {
        "title": (tag.title or filename_fallback).strip(),
        "artist": (tag.artist or "Unknown").strip(),
        "album": (tag.album or "Unknown").strip(),
        "genre": (tag.genre or "Unknown").strip(),
        "year": year
    }
    return res

def check_metadata_changed(filepath: str, track: Any) -> bool:
    """
    DBの値と現在のファイルタグを比較する。
    """
    try:
        tag = TinyTag.get(filepath)
        current_meta = extract_metadata_smart(filepath, tag)
        
        # タイトル、アーティスト、アルバムに変化があるかチェック
        if current_meta["title"] != (track.title or "").strip():
            return True
        if current_meta["artist"] != (track.artist or "").strip():
            return True
        if current_meta["album"] != (track.album or "").strip():
            return True
        if current_meta.get("year") != track.year:
            return True
            
        return False
    except Exception as e:
        print(f"DEBUG: Error in check_metadata_changed: {e}")
        return False

def update_file_metadata(filepath: str, lyrics: Optional[str] = None, artwork_b64: Optional[str] = None) -> bool:
    """Mutagenを使用して物理ファイルにメタデータを書き込む"""
    try:
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".mp3":
            audio = ID3(filepath)
            if lyrics is not None:
                audio.delall("USLT")
                audio.add(USLT(encoding=3, lang='eng', desc='', text=lyrics))
            if artwork_b64:
                img_data = base64.b64decode(artwork_b64)
                audio.delall("APIC")
                audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img_data))
            audio.save()
        elif ext == ".m4a":
            audio = MP4(filepath)
            if lyrics is not None:
                audio["\xa9lyr"] = [lyrics]
            if artwork_b64:
                img_data = base64.b64decode(artwork_b64)
                audio["covr"] = [MP4Cover(img_data, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
        elif ext == ".flac":
            audio = FLAC(filepath)
            if lyrics is not None:
                audio["lyrics"] = lyrics
            if artwork_b64:
                img_data = base64.b64decode(artwork_b64)
                picture = Picture()
                picture.data = img_data
                picture.type = 3
                picture.mime = "image/jpeg"
                audio.clear_pictures()
                audio.add_picture(picture)
            audio.save()
        else:
            return False
        return True
    except Exception as e:
        print(f"Failed to update file metadata: {e}")
        return False

def update_file_genre(filepath: str, genre: str) -> bool:
    """ジャンルのみ更新"""
    try:
        f = mutagen.File(filepath, easy=True)
        if f is not None:
            f['genre'] = [genre]
            f.save()
            return True
        return False
    except Exception as e:
        print(f"Error updating genre: {e}")
        return False

def update_file_tags_extended(filepath: str, title: str = None, artist: str = None, 
                              album: str = None, year: int = None, genre: str = None, 
                              lyrics: str = None) -> bool:
    try:
        # 1. Update Basic Tags
        f = mutagen.File(filepath, easy=True)
        if f is not None:
            if title: f['title'] = [title]
            if artist: f['artist'] = [artist]
            if album: f['album'] = [album]
            if year: f['date'] = [str(year)]
            if genre: f['genre'] = [genre]
            f.save()
        
        # 2. Update Lyrics
        if lyrics is not None:
            update_file_metadata(filepath, lyrics=lyrics)
            
        return True
    except Exception as e:
        print(f"Error updating extended tags: {e}")
        return False