import os
import unicodedata
from typing import Optional

def resolve_path(path: str) -> Optional[str]:
    """
    パスの存在確認を行い、見つからない場合はUnicode正規化(NFC/NFD)を試して解決する
    MacOS (NFD) と Linux/Web (NFC) の差異を吸収するため
    """
    if os.path.exists(path):
        return path
    
    # Try NFC (Standard for Linux/Web)
    nfc_path = unicodedata.normalize('NFC', path)
    if os.path.exists(nfc_path):
        return nfc_path
        
    # Try NFD (Standard for MacOS)
    nfd_path = unicodedata.normalize('NFD', path)
    if os.path.exists(nfd_path):
        return nfd_path
        
    return None
