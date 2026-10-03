from contextlib import contextmanager

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine, event

metadata = MetaData()
sessions = Table("sessions", metadata, Column("id", String, primary_key=True), Column("spec", Text, nullable=False), Column("state", Text, nullable=False), Column("token_hash", String, nullable=False, default=""))
snapshots = Table("snapshots", metadata, Column("session_id", String, primary_key=True), Column("seq", Integer, primary_key=True), Column("state", Text, nullable=False))
events = Table("events", metadata, Column("session_id", String, primary_key=True), Column("seq", Integer, primary_key=True), Column("content", Text, nullable=False))
actions = Table("actions", metadata, Column("session_id", String, primary_key=True), Column("key", String, primary_key=True), Column("request_hash", String, nullable=False), Column("result", Text, nullable=False))
objects = Table("objects", metadata, Column("id", String, primary_key=True), Column("session_id", String, nullable=False), Column("kind", String, nullable=False), Column("content", Text, nullable=False))


class Database:
    def __init__(self, url: str):
        self.engine = create_engine(url, connect_args={"timeout": 30} if url.startswith("sqlite") else {})
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

