import json
import os
import logging
from typing import List, Dict
from sqlmodel import Session
from utils.llm import generate_text

logger = logging.getLogger(__name__)

# パス設定
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_FILE = "genre_expansion_cache.json"
CACHE_PATH = os.path.join(DATA_DIR, CACHE_FILE)
INITIAL_JSON_PATH = os.path.join(DATA_DIR, "genres.json")

class GenreExpander:
    """
    指定されたジャンルのサブジャンルや関連ジャンルを展開するクラス。
    LLMに問い合わせた結果をローカルJSONにキャッシュし、自己成長するデータベースとして機能する。
    """
    def __init__(self):
        self.cache: Dict[str, List[str]] = {}
        self._load_cache()

    def _load_cache(self):
        """ロード: キャッシュファイルがあればそれを、なければ初期JSONを読み込む"""
        if not os.path.exists(DATA_DIR):
            try:
                os.makedirs(DATA_DIR)
            except Exception as e:
                logger.error(f"Failed to create data directory: {e}")

        # 1. キャッシュファイルの読み込み
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load genre cache: {e}")
                self.cache = {}
        
        # 2. 初期JSONの内容をマージ（キャッシュにある場合も統合）
        if os.path.exists(INITIAL_JSON_PATH):
            try:
                with open(INITIAL_JSON_PATH, "r", encoding="utf-8") as f:
                    initial_data = json.load(f)
                    for k, v in initial_data.items():
                        if k in self.cache:
                            # 既存キャッシュと初期データをマージして重複排除
                            merged = list(set(self.cache[k] + v))
                            self.cache[k] = merged
                        else:
                            self.cache[k] = v
            except Exception as e:
                logger.warning(f"Failed to load initial genres.json: {e}")

    def _save_cache(self):
        """学習したジャンル関係を永続化"""
        try:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save genre cache: {e}")

    def expand(self, session: Session, genre: str) -> List[str]:
        """
        ジャンルを拡張する。
        キャッシュにあればそれを返し、なければLLMに問い合わせて学習する。
        """
        if not genre:
            return []

        # キャッシュヒット (完全一致)
        if genre in self.cache:
            return list(set([genre] + self.cache[genre]))

        # キャッシュヒット (正規化マッチ: 大文字小文字・スペース無視)
        # 例: "Hiphop" -> "Hip Hop"
        normalized_input = genre.lower().replace(" ", "").replace("-", "")
        for key in self.cache.keys():
            normalized_key = key.lower().replace(" ", "").replace("-", "")
            if normalized_input == normalized_key:
                # マッチしたキーのリストを返す（入力されたgenre自体も追加）
                return list(set([genre] + self.cache[key]))
        
        # キャッシュミス: LLMに問い合わせ
        logger.info(f"Expanding unknown genre with LLM: {genre}")
        sub_genres = self._ask_llm(session, genre)
        
        # 結果を保存 (空リストでも保存して再問い合わせを防ぐ)
        self.cache[genre] = sub_genres
        self._save_cache()
        
        return list(set([genre] + sub_genres))

    def _ask_llm(self, session: Session, genre: str) -> List[str]:
        """
        Llama 3 などのローカルモデル向けに最適化したプロンプトでサブジャンルを聞く
        """
        prompt = f"""
        You are a music taxonomy expert.
        Task: List 5 to 10 distinct sub-genres or closely related styles for the music genre "{genre}".
        
        Rules:
        1. Return ONLY a raw JSON list of strings.
        2. Do not include explanations, markdown formatting, or polite phrases.
        3. If the genre is specific (e.g. "Minimal Techno"), list sibling styles or parent styles.
        4. If the genre is ambiguous or unknown, return an empty list [].
        5. Use standard English genre names.
        
        Example Output: ["Deep House", "Tech House", "Progressive House"]
        
        Target Genre: "{genre}"
        JSON:
        """
        
        try:
            response = generate_text(session, prompt)
            
            # クリーニングとパース
            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            
            cleaned = cleaned.strip()

            start = cleaned.find("[")
            end = cleaned.rfind("]")
            
            if start != -1 and end != -1:
                json_str = cleaned[start:end+1]
                result = json.loads(json_str)
                if isinstance(result, list):
                    return [str(r) for r in result if isinstance(r, (str, int, float))]
            
            logger.warning(f"LLM response did not contain a valid JSON list: {response}")
            return []
            
        except Exception as e:
            logger.error(f"Failed to parse LLM response for genre expansion: {e}")
            return []

genre_expander = GenreExpander()