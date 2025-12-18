import duckdb
import os
import sys

# パス設定: 環境に合わせて調整してください
# Dockerコンテナ内で実行する場合はデフォルトのままで動作する想定です
NEW_DB_PATH = os.getenv("DB_PATH", "djaly.duckdb")
BACKUP_DB_PATH = "djaly_backup.duckdb" # カレントディレクトリにあると仮定

def migrate():
    print(f"--- Djaly Data Migration Tool ---")
    print(f"Target DB (New): {NEW_DB_PATH}")
    print(f"Source DB (Old): {BACKUP_DB_PATH}")

    # ファイル存在確認
    if not os.path.exists(BACKUP_DB_PATH):
        print(f"[Error] Backup file '{BACKUP_DB_PATH}' not found.")
        print("既存の 'djaly.duckdb' を 'djaly_backup.duckdb' にリネームして配置してください。")
        sys.exit(1)

    if not os.path.exists(NEW_DB_PATH):
        print(f"[Error] New DB '{NEW_DB_PATH}' not found.")
        print("アプリを一度起動して、新しいDBスキーマを生成してから実行してください。")
        sys.exit(1)

    try:
        # 新しいDBに接続
        con = duckdb.connect(NEW_DB_PATH)
        
        # バックアップDBをアタッチ (Read-only)
        print("Attaching backup database...")
        con.execute(f"ATTACH '{BACKUP_DB_PATH}' AS old_db (READ_ONLY);")

        # 移行対象テーブル
        # FK制約はなくなりましたが、論理的な整合性のために親テーブルから順に処理します
        target_tables = [
            "tracks",
            "track_analyses",
            "track_embeddings", 
            "setlists",
            "setlist_tracks",
            "settings",
            "prompts",
            "presets"
        ]

        # 1. 新DBの初期データ(Seed)をクリア
        # (IDの衝突を防ぎ、バックアップの状態を完全に復元するため)
        print("Clearing initial seed data from new DB...")
        for table in reversed(target_tables):
            con.execute(f"DELETE FROM {table};")

        # 2. データのコピー
        print("Copying data from backup...")
        for table in target_tables:
            try:
                # バックアップ側にテーブルが存在するか確認
                # old_db.information_schema.tables が直接参照できない場合があるため、
                # information_schema.tables から table_catalog でフィルタリング
                table_exists = con.execute(
                    f"SELECT count(*) FROM information_schema.tables WHERE table_catalog = 'old_db' AND table_name = '{table}'"
                ).fetchone()[0] > 0

                if table_exists:
                    # カラムの共通部分を取得してINSERT文を構築する
                    # (スキーマ変更に対応するため)
                    
                    # 新DBのカラム
                    # table_catalog != 'old_db' でフィルタリング
                    new_cols_res = con.execute(
                        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' AND table_catalog != 'old_db'"
                    ).fetchall()
                    new_cols = set(r[0] for r in new_cols_res)
                    
                    # 旧DBのカラム
                    old_cols_res = con.execute(
                        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' AND table_catalog = 'old_db'"
                    ).fetchall()
                    old_cols = set(r[0] for r in old_cols_res)
                    
                    common_cols = list(new_cols.intersection(old_cols))
                    
                    if not common_cols:
                        print(f" [SKIP] {table}: No common columns found.")
                        continue
                        
                    # カラム名をクォートする（予約語対策など）
                    cols_str = ", ".join([f'"{c}"' for c in common_cols])
                    
                    con.execute(f"INSERT INTO {table} ({cols_str}) SELECT {cols_str} FROM old_db.main.{table};")
                    
                    count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    print(f" [OK] {table}: {count} rows migrated.")
                else:
                    print(f" [SKIP] {table}: Not found in backup.")
            except Exception as e:
                print(f" [ERROR] Failed to migrate {table}: {e}")

        # 3. シーケンス値のリセット (ID自動採番の整合性を取る)
        print("Resetting ID sequences...")
        seq_map = {
            "tracks": "track_id_seq",
            "setlists": "setlist_id_seq",
            "setlist_tracks": "setlist_track_id_seq",
            "prompts": "prompt_id_seq",
            "presets": "preset_id_seq"
        }

        for table, seq in seq_map.items():
            try:
                # 現在の最大IDを取得
                max_id_result = con.execute(f"SELECT MAX(id) FROM {table}").fetchone()
                max_id = max_id_result[0] if max_id_result and max_id_result[0] is not None else 0
                
                if max_id is not None:
                    # DuckDBのバージョンによっては ALTER SEQUENCE RESTART が未実装、setvalも存在しない場合があるため
                    # CREATE OR REPLACE SEQUENCE で再作成する
                    con.execute(f"CREATE OR REPLACE SEQUENCE {seq} START {max_id + 1};")
                    print(f" -> Sequence {seq} reset to start from {max_id + 1}")
            except Exception as e:
                print(f"Warning: Could not reset sequence for {table}: {e}")

        con.close()
        print("\nMigration completed successfully!")
        print("You can now restart the application.")

    except Exception as e:
        print(f"\nFatal Error during migration: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate()