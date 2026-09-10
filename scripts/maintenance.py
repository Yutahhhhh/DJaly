"""Developer maintenance commands using the application's platform-specific paths."""
from pathlib import Path
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from config import Settings


def copy_database(source, destination):
    import duckdb
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.resolve() == destination.resolve():
        raise ValueError("Source and destination must differ")
    # Keep the source locked throughout the snapshot. Windows does not permit
    # shutil.copy while DuckDB owns the file; COPY FROM DATABASE preserves the
    # schema, data, views and sequences without a second filesystem reader.
    with duckdb.connect(str(source)) as connection:
        connection.execute("CHECKPOINT")
        if destination.exists():
            saved = destination.with_name(destination.name + f".{time.time_ns()}.bak")
            copy_database(destination, saved)
            print(f"Previous database saved: {saved}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + f".{time.time_ns()}.copying")
        try:
            database = connection.execute("SELECT current_database()").fetchone()[0].replace('"', '""')
            quoted_path = str(temporary).replace("'", "''")
            connection.execute(f"ATTACH '{quoted_path}' AS plumdeck_snapshot")
            connection.execute(f'COPY FROM DATABASE "{database}" TO plumdeck_snapshot')
            connection.execute("CHECKPOINT plumdeck_snapshot")
            connection.execute("DETACH plumdeck_snapshot")
            os.replace(temporary, destination)
        finally:
            # Also releases the snapshot file on a failed COPY before cleanup.
            connection.close()
            temporary.unlink(missing_ok=True)
            Path(str(temporary) + ".wal").unlink(missing_ok=True)
    print(destination)


def main():
    settings = Settings(_env_file=None)
    production = Path(settings.DB_PATH)
    development = ROOT / "db_data/plumdeck.duckdb"
    backup = ROOT / "backup/plumdeck.duckdb"
    command = sys.argv[1]
    if command == "backup":
        copy_database(production, backup)
    elif command == "restore":
        copy_database(development, production)
    elif command in ("local-restore", "prod-restore"):
        subprocess.run([sys.executable, str(ROOT / "backend/transfer_db.py"), str(backup),
                        str(development if command == "local-restore" else production)], check=True)
    elif command == "db-cli":
        subprocess.run([sys.executable, "-m", "harlequin", "-r", str(development)], check=True)
    elif command == "log-watch":
        log = Path(settings.PLUMDECK_LOG_DIR) / "plumdeck.log"
        print(f"Watching {log}", flush=True)
        position = 0
        while True:
            if log.exists():
                with log.open("rb") as stream:
                    if log.stat().st_size < position:
                        position = 0
                    stream.seek(position)
                    data = stream.read()
                    position = stream.tell()
                if data:
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
            time.sleep(.5)
    elif command in ("clean-db", "clean-wal"):
        # Preserve a recoverable copy for these explicitly destructive commands.
        if production.exists():
            copy_database(production, backup)
        if command == "clean-db":
            production.unlink(missing_ok=True)
        Path(str(production) + ".wal").unlink(missing_ok=True)
    else:
        raise ValueError(f"Unknown maintenance command: {command}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
