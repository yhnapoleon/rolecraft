"""Historical r3 test-only persistence double. Never imported by product code.

Keeps old domain regression fixtures reproducible; official integration tests use
Gateway/V2Store. This is not evidence of W01 persistence correctness.
"""
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import Table, Column, MetaData, String, Text, Integer, insert, select
from sqlalchemy.engine import Engine

from career_lab.contracts.v2.core import AuthContext, Command, ProtocolError, canonical, digest
from career_lab.contracts.v2.research import StoredObject
from career_lab.workspace.ports import Snapshot, authorize

metadata = MetaData()
versions = Table('w03_workspace_versions', metadata,
    Column('session_id',String,primary_key=True), Column('kind',String,primary_key=True),
    Column('object_id',String,primary_key=True), Column('version',Integer,primary_key=True),
    Column('content',Text,nullable=False))
requests = Table('w03_workspace_requests', metadata,
    Column('session_id',String,primary_key=True), Column('request_id',String,primary_key=True),
    Column('request_hash',String,nullable=False), Column('result',Text,nullable=False))
audits = Table('w03_workspace_audit', metadata,
    Column('session_id',String,primary_key=True), Column('storage_revision',Integer,primary_key=True),
    Column('content',Text,nullable=False))


def register_tables(engine: Engine) -> None:
    metadata.create_all(engine)


class WorkspaceRepository:
    def __init__(self, engine: Engine, authority, clock=None):
        self.engine, self.authority = engine, authority
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @contextmanager
    def transaction(self, *, write=False):
        with self.engine.connect() as conn:
            if write and conn.dialect.name == 'sqlite': conn.exec_driver_sql('BEGIN IMMEDIATE')
            else: conn.begin()
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def _snapshot(self, conn, auth, *, lock=False):
        self.authority.validate(conn, auth)
        state = self.authority.state(conn, auth, lock=lock)
        if state.session_id != auth.session_id: raise ProtocolError('not_found', status=404)
        rows = conn.execute(select(versions.c.content).where(versions.c.session_id == auth.session_id)).scalars()
        objects = tuple(StoredObject.model_validate_json(row) for row in rows)
        return Snapshot(state, objects, lambda ref: self.authority.can_reference(conn, auth, ref),
                        self.authority.roles(conn, auth))

    def read(self, auth, query):
        authorize(auth, self.clock())
        with self.transaction() as conn:
            return query(self._snapshot(conn, auth))

    def execute(self, auth: AuthContext, command: Command, handler):
        now = self.clock(); authorize(auth, now, command.operation)
        # Preview has no ledger writes and can run with read-only credentials.
        fingerprint = digest({'command': command.model_dump(mode='json'),
            'actor': auth.actor_id, 'executor': auth.executor.model_dump(mode='json'),
            'credential_id': auth.credential_id, 'allowed_objects': auth.allowed_objects,
            'allowed_actions': auth.allowed_actions})
        with self.transaction(write=True) as conn:
            snapshot = self._snapshot(conn, auth, lock=True)
            old = conn.execute(select(requests).where(requests.c.session_id == auth.session_id,
                                                      requests.c.request_id == command.request_id)).mappings().first()
            if old:
                if old['request_hash'] != fingerprint: raise ProtocolError('request_id_reused', status=409)
                import json
                return json.loads(old['result'])
            if snapshot.state.status != 'active': raise ProtocolError('session_'+snapshot.state.status)
            if (command.expected_version != snapshot.state.business_seq
                    or command.expected_workspace_revision != snapshot.state.workspace_revision):
                raise ProtocolError('version_conflict', status=409)
            mutation = handler(snapshot, auth, command, now)
            heads = {(o.ref.kind,o.ref.object_id):o.ref.version for kind in {o.ref.kind for o in snapshot.objects}
                     for o in snapshot.heads(kind)}
            for obj in mutation.writes:
                if obj.ref.session_id != auth.session_id or obj.created_storage_revision != snapshot.next_point.storage_revision:
                    raise ProtocolError('invalid_mutation')
                previous = heads.get((obj.ref.kind,obj.ref.object_id),0)
                if obj.ref.version != previous+1: raise ProtocolError('object_version_conflict', status=409)
                heads[(obj.ref.kind,obj.ref.object_id)]=obj.ref.version
                conn.execute(insert(versions).values(session_id=auth.session_id,kind=obj.ref.kind,
                    object_id=obj.ref.object_id,version=obj.ref.version,content=obj.model_dump_json()))
            if mutation.writes:
                self.authority.advance_workspace(conn, auth, snapshot.state, snapshot.next_point)
                conn.execute(insert(audits).values(session_id=auth.session_id,
                    storage_revision=snapshot.next_point.storage_revision,
                    content=canonical({'operation':mutation.event_type,'refs':[o.ref.model_dump(mode='json') for o in mutation.writes],
                        'executor':auth.executor.model_dump(mode='json'),'actor_id':auth.actor_id,'at':now.isoformat(),
                        'as_of':snapshot.next_point.model_dump(mode='json')})))
            conn.execute(insert(requests).values(session_id=auth.session_id,request_id=command.request_id,
                request_hash=fingerprint,result=canonical(mutation.result)))
            return mutation.result
