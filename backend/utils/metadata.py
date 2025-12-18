import os
import base64
from typing import Dict, Optional, Any
from tinytag import TinyTag
import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, USLT, APIC
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture

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
    """ファイル名等からメタデータを補完する"""
    if tag is None:
        try:
            tag = TinyTag.get(filepath)
        except:
            tag = TinyTag(None, 0)

    res = {
        "title": tag.title or os.path.splitext(os.path.basename(filepath))[0],
        "artist": tag.artist or "Unknown",
        "album": tag.album or "Unknown",
        "genre": tag.genre or "Unknown"
    }
    return res

def update_file_metadata(filepath: str, lyrics: Optional[str] = None, artwork_b64: Optional[str] = None) -> bool:
    """
    Mutagenを使用して物理ファイルに歌詞(USLT等)やアートワーク(APIC等)を直接書き込む。
    MP3, FLAC, M4Aをサポート。
    """
    try:
        ext = os.path.splitext(filepath)[1].lower()
        
        # --- MP3 (ID3) ---
        if ext == ".mp3":
            audio = ID3(filepath)
            if lyrics is not None:
                audio.delall("USLT")
                audio.add(USLT(encoding=3, lang='eng', desc='desc', text=lyrics))
            if artwork_b64:
                img_data = base64.b64decode(artwork_b64)
                audio.delall("APIC")
                audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img_data))
            audio.save()

        # --- M4A (MP4) ---
        elif ext == ".m4a":
            audio = MP4(filepath)
            if lyrics is not None:
                audio["\xa9lyr"] = [lyrics]
            if artwork_b64:
                img_data = base64.b64decode(artwork_b64)
                audio["covr"] = [MP4Cover(img_data, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()

        # --- FLAC ---
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
            print(f"Unsupported format for metadata update: {ext}")
            return False
            
        return True
    except Exception as e:
        print(f"Failed to update file metadata: {e}")
        return False

def check_metadata_changed(filepath: str, track: Any) -> bool:
    """変更があるかチェック"""
    try:
        tag = TinyTag.get(filepath)
        if (tag.title or "") != (track.title or ""): return True
        if (tag.artist or "") != (track.artist or ""): return True
        return False
    except:
        return False

def update_file_genre(filepath: str, genre: str) -> bool:
    """ジャンルのみ更新（EasyID3等を使用）"""
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