from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine, event

metadata = MetaData()
sessions = Table(
    "sessions",
    metadata,
    Column("id", String, primary_key=True),
    Column("spec", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("token_hash", String, nullable=False, default=""),
)
snapshots = Table(
    "snapshots",
    metadata,
    Column("session_id", String, primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("state", Text, nullable=False),
)
events = Table(
    "events",
    metadata,
    Column("session_id", String, primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("content", Text, nullable=False),
)
actions = Table(
    "actions",
    metadata,
    Column("session_id", String, primary_key=True),
    Column("key", String, primary_key=True),
    Column("request_hash", String, nullable=False),
    Column("result", Text, nullable=False),
)
objects = Table(
    "objects",
    metadata,
    Column("id", String, primary_key=True),
    Column("session_id", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("content", Text, nullable=False),
)
event_times = Table(
    "event_times",
    metadata,
    Column("session_id", String, primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("created_at", String, nullable=False),
)
object_times = Table(
    "object_times",
    metadata,
    Column("session_id", String, primary_key=True),
    Column("id", String, primary_key=True),
    Column("created_at", String, nullable=False),
)
object_metadata = Table(
    "object_metadata",
    metadata,
    Column("session_id", String, primary_key=True),
    Column("id", String, primary_key=True),
    Column("content", Text, nullable=False),
)
job_times = Table(
    "job_times",
    metadata,
    Column("id", String, primary_key=True),
    Column("queued_at", String),
    Column("started_at", String),
    Column("finished_at", String),
)


def utc_timestamp(now: float | None = None) -> str:
    """UTC metadata only: never part of an action or evidence fingerprint."""
    instant = (
        datetime.now(timezone.utc) if now is None else datetime.fromtimestamp(now, timezone.utc)
    )
    return instant.isoformat(timespec="microseconds").replace("+00:00", "Z")


class Database:
    def __init__(self, url: str):
        self.engine = create_engine(
            url, connect_args={"timeout": 30} if url.startswith("sqlite") else {}
        )
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def configure(dbapi_connection, _):
                dbapi_connection.execute("PRAGMA journal_mode=WAL")

        metadata.create_all(self.engine)

    @contextmanager
    def transaction(self):
        with self.engine.connect() as connection:
            if self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
