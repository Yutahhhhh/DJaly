from concurrent.futures import ThreadPoolExecutor
import threading

from sqlalchemy import event, text

from infra.database.connection import create_library_engine


def test_library_connection_reuses_handles_during_search_and_analysis_writes(tmp_path):
    engine = create_library_engine(f"duckdb:///{tmp_path / 'concurrent.duckdb'}")
    connections = []
    event.listen(engine, "connect", lambda dbapi, record: connections.append(dbapi))
    try:
        with engine.begin() as con:
            # Match production: stored JSON text, cast only during similarity search.
            con.execute(text("CREATE TABLE vectors (id INTEGER PRIMARY KEY, value VARCHAR)"))
            con.execute(text("INSERT INTO vectors VALUES (1, '[1,2,3]'), (2, '[3,2,1]')"))
        barrier = threading.Barrier(6)
        write_lock = threading.Lock()

        def exercise(worker):
            barrier.wait(timeout=10)
            for index in range(40):
                if worker < 2:
                    with write_lock, engine.begin() as con:
                        con.execute(text("UPDATE vectors SET value=:vec WHERE id=:id"),
                                    {"vec": f"[1,2,{index + 1}]", "id": worker + 1})
                else:
                    with engine.begin() as con:
                        rows = con.execute(text("SELECT id, array_cosine_similarity(value::FLOAT[3], [1,2,3]::FLOAT[3]) FROM vectors ORDER BY 2 DESC")).all()
                        assert len(rows) == 2
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(exercise, range(6)))
        assert 1 <= len(connections) <= 6
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_library_connection_recovers_after_rolled_back_query(tmp_path):
    engine = create_library_engine(f"duckdb:///{tmp_path / 'rollback.duckdb'}")
    try:
        try:
            with engine.begin() as con:
                con.execute(text("SELECT * FROM absent_table"))
        except Exception:
            pass
        with engine.connect() as con:
            assert con.execute(text("SELECT 42")).scalar_one() == 42
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_long_session_does_not_block_an_independent_search(tmp_path):
    engine = create_library_engine(f"duckdb:///{tmp_path / 'independent.duckdb'}")
    try:
        with engine.connect() as held:
            assert held.execute(text("SELECT 1")).scalar_one() == 1

            def search():
                with engine.connect() as other:
                    return other.execute(text("SELECT 2")).scalar_one()

            with ThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(search).result(timeout=10) == 2
    finally:
        engine.dispose()
