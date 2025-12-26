#!/usr/bin/env python3
"""
ジャンルデータパッチスクリプト
サブジャンルを親ジャンルにマッピングし、tracksテーブルを更新します。
"""

import sys
import duckdb
from typing import Dict

# 親ジャンルへのマッピング定義
GENRE_MAP: Dict[str, str] = {
    # --- House ---
    "Acid House": "House",
    "Afro House": "House",
    "Bass House": "House",
    "Big Room House": "House",
    "Chill House": "House",
    "Circuit House": "House",
    "Dance House": "House",
    "Deep House": "House",
    "Disco House": "House",
    "Electro House": "House",
    "French House": "House",
    "Funk House": "House",
    "Funky House": "House",
    "Future House": "House",
    "Garage House": "House",
    "Groove House": "House",
    "House": "House",
    "Italo House": "House",
    "Jackin House": "House",
    "Jacking House": "House",
    "Jazz House": "House",
    "Latin House": "House",
    "Lounge House": "House",
    "Melodic House": "House",
    "Organic House": "House",
    "Phonk House": "House",
    "Piano House": "House",
    "Progressive House": "House",
    "Slap House": "House",
    "Soulful House": "House",
    "Tech House": "House",
    "Tribal House": "House",
    "Tropical House": "House",
    "Vocal House": "House",

    # --- Techno & Trance ---
    "Big Room Techno": "Techno",
    "Melodic Techno": "Techno",
    "Minimal Techno": "Techno",
    "Techno": "Techno",
    "Progressive Trance": "Trance",
    "Psytrance": "Trance",
    "Trance": "Trance",

    # --- Bass / Garage / D&B ---
    "Bass Music": "Bass",
    "Breakbeat": "Bass",
    "Drum & Bass": "Bass",
    "Dubstep": "Bass",
    "Garage": "Bass",
    "Jersey Club": "Bass",
    "Juke": "Bass",
    "Melodic Dubstep": "Bass",
    "UK Bass": "Bass",
    "UK Bassline": "Bass",
    "UK Funky": "Bass",
    "UK Garage": "Bass",
    "UK Hardcore": "Bass",
    "Future Bass": "Bass",

    # --- Hip Hop / Rap / Trap ---
    "Alternative Hip Hop": "Hip Hop",
    "Christian Hip Hop": "Hip Hop",
    "Electronic Hip Hop": "Hip Hop",
    "French Hip Hop": "Hip Hop",
    "Hardcore Hip Hop": "Hip Hop",
    "Hip Hop": "Hip Hop",
    "Latin Hip Hop": "Hip Hop",
    "Swedish Hip Hop": "Hip Hop",
    "Drill": "Hip Hop",
    "UK Drill": "Hip Hop",
    "Grime": "Hip Hop",
    "Rap": "Hip Hop",
    "Melodic Rap": "Hip Hop",
    "Pop Rap": "Hip Hop",
    "UK Rap": "Hip Hop",
    "Jazz Rap": "Hip Hop",
    "Trap": "Hip Hop",
    "Chill Trap": "Hip Hop",
    "Festival Trap": "Hip Hop",
    "Hybrid Trap": "Hip Hop",
    "Latin Trap": "Hip Hop",
    "Crunk": "Hip Hop",
    "Emo Rap": "Hip Hop",

    # --- R&B / Soul ---
    "R&B": "R&B",
    "Electronic R&B": "R&B",
    "Future R&B": "R&B",
    "Latin R&B": "R&B",
    "Pop R&B": "R&B",
    "Soul": "R&B",
    "Soul Pop": "R&B",
    "Neo-Soul": "R&B",
    "Gospel": "R&B",
    "Gospel House": "R&B",

    # --- Funk / Disco ---
    "Funk": "Funk",
    "Disco": "Funk",
    "Disco Funk": "Funk",
    "Disco Soul": "Funk",
    "Nu Disco": "Funk",

    # --- Reggae / Dancehall / Afrobeat ---
    "Reggae": "Reggae",
    "J-Reggae": "Reggae",
    "Reggae Fusion": "Reggae",
    "Dancehall": "Reggae",
    "Dancehall Pop": "Reggae",
    "Afrobeat": "Reggae",
    "Afrobeats": "Reggae",
    "Soca": "Reggae",

    # --- Latin / Tropical ---
    "Latin": "Latin",
    "Latin Dance": "Latin",
    "Latin Urban": "Latin",
    "Electro Latino": "Latin",
    "Reggaeton": "Latin",
    "Cubaton": "Latin",
    "Dembow": "Latin",
    "Bachata": "Latin",
    "Salsa": "Latin",
    "Merengue": "Latin",
    "Cumbia": "Latin",
    "Guaracha": "Latin",
    "Baile Funk": "Latin",
    "Funk Carioca": "Latin",
    "Sertanejo": "Latin",
    "Flamenco": "Latin",

    # --- Pop ---
    "Pop": "Pop",
    "Dance Pop": "Pop",
    "EDM Pop": "Pop",
    "Electro Pop": "Pop",
    "Electronic Pop": "Pop",
    "Future Pop": "Pop",
    "Indie Pop": "Pop",
    "Synth Pop": "Pop",
    "Synthpop": "Pop",
    "J-Pop": "Pop",
    "K-Pop": "Pop",
    "Latin Pop": "Pop",
    "Mandopop": "Pop",
    "Brazilian Pop": "Pop",
    "Chill Pop": "Pop",
    "Christian Pop": "Pop",
    "Country Pop": "Pop",
    "Folk Pop": "Pop",
    "French Pop": "Pop",
    "Tropical Pop": "Pop",
    "Urban Pop": "Pop",
    "World Pop": "Pop",
    "Traditional Pop": "Pop",

    # --- Rock / Alternative ---
    "Alternative Metal": "Rock",
    "J-Rock": "Rock",
    "Pop Rock": "Rock",
    "Rap Rock": "Rock",
    "Soft Rock": "Rock",
    "Indie Rock": "Rock",
    "Pop Punk": "Rock",
    "New Wave": "Rock",

    # --- EDM / Electronic ---
    "EDM": "Electronic",
    "Electronic": "Electronic",
    "Electronic Dance Music": "Electronic",
    "Electro": "Electronic",
    "Eurodance": "Electronic",
    "Big Room": "Electronic",
    "Club": "Electronic",
    "Dance": "Electronic",
    "Freestyle": "Electronic",
    "Future Rave": "Electronic",
    "Future Bounce": "Electronic",
    "Future Funk": "Electronic",
    "Hands Up": "Electronic",
    "Hardstyle": "Electronic",
    "Hard Dance": "Electronic",
    "Hardcore": "Electronic",
    "Indie Dance": "Electronic",
    "Indie Electronic": "Electronic",
    "Melbourne Bounce": "Electronic",
    "Moombahton": "Electronic",
    "Moombah": "Electronic",
    "Moombahcore": "Electronic",
    "Midtempo": "Electronic",
    "Midtempo Bass": "Electronic",
    "Industrial": "Electronic",
    "Synthwave": "Electronic",
    "World Electronic": "Electronic",

    # --- Downtempo / Chill ---
    "Ambient": "Downtempo",
    "Chill": "Downtempo",
    "Chillhop": "Downtempo",
    "Chillout": "Downtempo",
    "Chillwave": "Downtempo",
    "Downtempo": "Downtempo",
    "Lo-fi": "Downtempo",
    "Lo-Fi Hip Hop": "Downtempo",
    "Lounge": "Downtempo",
    "Trip Hop": "Downtempo",

    # --- Jazz / Others ---
    "Jazz": "Jazz",
    "Vocal Jazz": "Jazz",
    "Nu Jazz": "Jazz",
    "Swing": "Jazz",
    "Electro Swing": "Jazz",
    "Country": "Country",
    "Contemporary Christian": "Other",
    "DJ Tool": "Other",
    "Global Music": "Other",
}

def get_parent_genre(sub_genre: str) -> str:
    """サブジャンルから親ジャンルを返す。見つからない場合は 'Other'"""
    return GENRE_MAP.get(sub_genre, "Other")


def patch_genres(db_path: str, dry_run: bool = False):
    """
    ジャンルデータパッチを実行
    
    Args:
        db_path: DuckDBファイルのパス
        dry_run: Trueの場合、実際の更新は行わずプレビューのみ
    """
    print(f"🎵 ジャンルデータパッチを開始します")
    print(f"📁 データベース: {db_path}")
    print(f"🔍 モード: {'DRY RUN (プレビューのみ)' if dry_run else '実行'}")
    print()

    # DuckDB接続
    conn = duckdb.connect(db_path)

    try:
        # 現在のジャンルの状態を確認
        print("📊 現在のジャンル状況を確認中...")
        current_genres = conn.execute("""
            SELECT DISTINCT genre, COUNT(*) as count
            FROM tracks
            GROUP BY genre
            ORDER BY count DESC
        """).fetchall()

        print(f"\n現在のジャンル数: {len(current_genres)}")
        print("\n現在のジャンル分布 (上位10件):")
        for genre, count in current_genres[:10]:
            print(f"  {genre}: {count}曲")

        # 更新対象を確認
        print("\n\n🔄 更新対象を確認中...")
        
        # 各トラックのジャンルについて、親ジャンルへの変更をシミュレート
        updates = {}
        for genre, count in current_genres:
            parent_genre = get_parent_genre(genre)
            if parent_genre != genre:
                updates[genre] = (parent_genre, count)

        if not updates:
            print("✅ 更新が必要なジャンルはありません")
            return

        print(f"\n更新対象: {len(updates)}個のジャンル")
        print("\n変更内容:")
        for old_genre, (new_genre, count) in sorted(updates.items(), key=lambda x: x[1][1], reverse=True):
            print(f"  {old_genre} → {new_genre} ({count}曲)")

        # 更新後の予測ジャンル分布
        predicted_distribution = {}
        for genre, count in current_genres:
            parent_genre = get_parent_genre(genre)
            predicted_distribution[parent_genre] = predicted_distribution.get(parent_genre, 0) + count

        print("\n\n📊 更新後の予測ジャンル分布:")
        for genre, count in sorted(predicted_distribution.items(), key=lambda x: x[1], reverse=True):
            print(f"  {genre}: {count}曲")

        if dry_run:
            print("\n\n🔍 DRY RUNモードのため、実際の更新は行いません")
            return

        # 実際の更新を実行
        print("\n\n💾 データベースを更新中...")
        
        # トランザクション開始
        conn.execute("BEGIN TRANSACTION")
        
        try:
            # 各ジャンルを親ジャンルに更新（subgenreは触らない）
            total_updated = 0
            for old_genre, (new_genre, count) in updates.items():
                result = conn.execute("""
                    UPDATE tracks
                    SET genre = ?
                    WHERE genre = ?
                """, [new_genre, old_genre])
                total_updated += count
                print(f"  ✓ {old_genre} → {new_genre} ({count}曲)")

            # コミット
            conn.execute("COMMIT")
            print(f"\n✅ 更新完了: {total_updated}曲のジャンルを更新しました")

        except Exception as e:
            conn.execute("ROLLBACK")
            print(f"\n❌ エラーが発生しました: {e}")
            raise

        # 更新後の状態を確認
        print("\n\n📊 更新後のジャンル状況:")
        final_genres = conn.execute("""
            SELECT DISTINCT genre, COUNT(*) as count
            FROM tracks
            GROUP BY genre
            ORDER BY count DESC
        """).fetchall()

        print(f"最終ジャンル数: {len(final_genres)}")
        for genre, count in final_genres:
            print(f"  {genre}: {count}曲")

    finally:
        conn.close()

    print("\n\n🎉 ジャンルデータパッチが完了しました!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ジャンルデータパッチスクリプト")
    parser.add_argument(
        "db_path",
        nargs="?",
        default="../db_data/djaly.duckdb",
        help="DuckDBファイルのパス (デフォルト: ../db_data/djaly.duckdb)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際の更新を行わず、プレビューのみ実行"
    )

    args = parser.parse_args()

    patch_genres(args.db_path, dry_run=args.dry_run)
