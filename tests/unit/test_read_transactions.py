"""SQLite readers retain a snapshot without reserving the only writer."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import text

from career_lab.storage.database import Database


def test_read_snapshot_survives_a_concurrent_committed_write(tmp_path: Path) -> None:
    db = Database("sqlite:///" + str(tmp_path / "read.db"))
    with db.transaction() as connection:
        connection.execute(text("CREATE TABLE sample (value INTEGER)"))
        connection.execute(text("INSERT INTO sample VALUES (1)"))

    def write():
        with db.transaction() as connection:
            connection.execute(text("UPDATE sample SET value = 2"))

    try:
        with db.transaction(write=False) as reader:
            assert reader.execute(text("SELECT value FROM sample")).scalar_one() == 1
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(write).result(timeout=5)
            assert reader.execute(text("SELECT value FROM sample")).scalar_one() == 1
        with db.transaction(write=False) as reader:
            assert reader.execute(text("SELECT value FROM sample")).scalar_one() == 2
    finally:
        db.engine.dispose()
