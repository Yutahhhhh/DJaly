import importlib.util
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[3]


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_preserves_database_and_previous_destination(tmp_path):
    maintenance = load_script("maintenance", "scripts/maintenance.py")
    source = tmp_path / "日本語 user's library.duckdb"
    target = tmp_path / "backup" / "library.duckdb"
    with duckdb.connect(str(source)) as connection:
        connection.execute("CREATE SEQUENCE ids START 12")
        connection.execute("CREATE TABLE tracks(id INTEGER DEFAULT nextval('ids'))")
        connection.execute("INSERT INTO tracks DEFAULT VALUES")
        connection.execute("CREATE VIEW track_view AS SELECT * FROM tracks")
    maintenance.copy_database(source, target)
    maintenance.copy_database(source, target)
    with duckdb.connect(str(target)) as connection:
        assert connection.execute("SELECT id FROM track_view").fetchone() == (12,)
        connection.execute("INSERT INTO tracks DEFAULT VALUES")
        assert connection.execute("SELECT id FROM tracks ORDER BY id").fetchall() == [(12,), (13,)]
    assert len(list(target.parent.glob("*.bak"))) == 1


def test_failed_migration_rolls_back_prior_tables(tmp_path):
    transfer = load_script("transfer_db", "backend/transfer_db.py")
    source = tmp_path / "日本語 user's old.duckdb"
    target = tmp_path / "new.duckdb"
    with duckdb.connect(str(source)) as connection:
        connection.execute("CREATE TABLE tracks AS SELECT 12 id")
        connection.execute("CREATE TABLE settings AS SELECT -1 id")
    with duckdb.connect(str(target)) as connection:
        connection.execute("CREATE TABLE tracks AS SELECT 42 id")
        connection.execute("CREATE TABLE settings(id INTEGER CHECK(id>0))")
        connection.execute("INSERT INTO settings VALUES(1)")
    with pytest.raises(duckdb.ConstraintException):
        transfer.migrate_data(str(source), str(target))
    with duckdb.connect(str(target)) as connection:
        assert connection.execute("SELECT id FROM tracks").fetchone() == (42,)
        assert connection.execute("SELECT id FROM settings").fetchone() == (1,)
