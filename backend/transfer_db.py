#!/usr/bin/env python3
import duckdb
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_table_columns(conn, table_name, db_alias="main"):
    """
    指定されたデータベース（エイリアス）のテーブルからカラム名リストを取得する。
    """
    try:
        res = conn.execute(f"DESCRIBE {db_alias}.{table_name}").fetchall()
        return [row[0] for row in res]
    except Exception as e:
        print(f"    Error fetching columns for {db_alias}.{table_name}: {e}")
        return []

def migrate_data(from_db_path: str, to_db_path: str):
    """
    旧DB (from_db_path) から新DB (to_db_path) へデータを移行する。
    """
    if not os.path.exists(from_db_path):
        print(f"Error: Source database not found at {from_db_path}")
        return

    print(f"Starting migration...")
    print(f"Source: {from_db_path}")
    print(f"Target: {to_db_path}")

    # ターゲットDB（新DB）に接続
    conn = duckdb.connect(to_db_path)

    try:
        # 1. 旧DBをマウント（読み取り専用）
        conn.execute(f"ATTACH '{from_db_path}' AS source_db (READ_ONLY);")

        # 2. 移行対象のテーブルリスト
        tables = [
            "tracks",
            "track_analyses",
            "track_embeddings",
            "lyrics",
            "prompts",
            "presets",
            "setlists",
            "setlist_tracks",
            "settings"
        ]

        for table in tables:
            print(f"  Migrating table: {table}...")
            
            target_cols = get_table_columns(conn, table, "main")
            source_cols = get_table_columns(conn, table, "source_db")
            common_cols = [c for c in target_cols if c in source_cols]
            
            if not common_cols:
                print(f"    Warning: No common columns found for {table}.")
                continue

            cols_str = ", ".join([f'"{c}"' for c in common_cols])
            conn.execute(f"DELETE FROM main.{table};")
            
            conn.execute(f"""
                INSERT INTO main.{table} ({cols_str}) 
                SELECT {cols_str} FROM source_db.{table};
            """)
            
            count = conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
            print(f"    Done. ({count} rows migrated)")

        # 3. シーケンスの同期
        # ALTER SEQUENCE が未実装の環境向けに nextval() の空回しで同期する
        sequences = {
            "seq_tracks_id": "tracks",
            "seq_prompts_id": "prompts",
            "seq_presets_id": "presets",
            "seq_setlists_id": "setlists",
            "seq_setlist_tracks_id": "setlist_tracks"
        }

        print("Synchronizing sequences using nextval pumping...")
        for seq, table in sequences.items():
            try:
                # 現在のテーブルの最大IDを取得
                max_id_res = conn.execute(f"SELECT MAX(id) FROM {table}").fetchone()
                max_id = max_id_res[0] if max_id_res and max_id_res[0] is not None else 0
                
                if max_id > 0:
                    # range(max_id) 行生成し、その数だけ nextval を叩いてシーケンスを進める
                    # これにより、次に nextval を呼ぶと max_id + 1 が返るようになる
                    conn.execute(f"SELECT count(nextval('{seq}')) FROM range({max_id});")
                    print(f"    Sequence {seq} advanced to {max_id}")
                else:
                    print(f"    Sequence {seq} skip (no data)")
            except Exception as seq_e:
                print(f"    Warning: Could not sync sequence {seq}: {seq_e}")

        print("\nMigration completed successfully!")
        print("You can now swap the database files.")

    except Exception as e:
        print(f"\nMigration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        current_script = os.path.basename(__file__)
        print(f"Usage: python backend/{current_script} <from_db_path> <to_db_path>")
    else:
        migrate_data(sys.argv[1], sys.argv[2])