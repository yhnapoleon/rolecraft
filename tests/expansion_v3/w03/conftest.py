"""Local module fixtures. Authority/auth are explicit test doubles, not W01 integration."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, MetaData, Table, Column, String, Text, insert, select, update

from career_lab.contracts.v2.core import AuthContext, Executor, Command, ProtocolError
from career_lab.contracts.v2.world import WorldStateV2
from legacy_repository_fixture import register_tables, WorkspaceRepository
from career_lab.workspace.service import WorkspaceService

test_metadata=MetaData()
test_states=Table('w03_test_authority',test_metadata,Column('id',String,primary_key=True),Column('state',Text))


class TestAuthority:
    __test__=False
    def __init__(self): self.revoked=set(); self.fail_after_advance=False; self.references=set()
    def validate(self,conn,auth):
        if auth.credential_id in self.revoked: raise ProtocolError('credential_revoked',status=401)
    def state(self,conn,auth,*,lock):
        q=select(test_states.c.state).where(test_states.c.id==auth.session_id)
        raw=conn.execute(q.with_for_update() if lock else q).scalar_one_or_none()
        if raw is None:raise ProtocolError('not_found',status=404)
        return WorldStateV2.model_validate_json(raw)
    def advance_workspace(self,conn,auth,before,after):
        new=before.model_copy(update={'workspace_revision':after.workspace_revision,'storage_revision':after.storage_revision})
        conn.execute(update(test_states).where(test_states.c.id==auth.session_id).values(state=new.model_dump_json()))
        if self.fail_after_advance: raise RuntimeError('injected after authoritative clock write')
    def can_reference(self,conn,auth,ref):
        return ref.session_id==auth.session_id and (ref.kind,ref.object_id,ref.version) in self.references
    def roles(self,conn,auth): return ('tech_lead','supervisor','business_lead')


@pytest.fixture
def env(tmp_path):
    engine=create_engine(f'sqlite:///{tmp_path / "w03.db"}',connect_args={'timeout':30})
    register_tables(engine);test_metadata.create_all(engine)
    authority=TestAuthority()
    with engine.begin() as conn:
        for sid in ['s','other']:
            state=WorldStateV2(session_id=sid,business_seq=7,workspace_revision=0,storage_revision=10,
                cycle_id='cycle-1',resources={'capacity':30,'dev_days':3},applied_milestones=('initial_plan_applied',))
            conn.execute(insert(test_states).values(id=sid,state=state.model_dump_json()))
    auth=AuthContext(session_id='s',actor_id='learner',executor=Executor(id='human-1',kind='human'),
        capabilities=('read','act'),credential_id='trusted-human')
    service=WorkspaceService(WorkspaceRepository(engine,authority,clock=lambda:datetime(2026,10,6,13,tzinfo=timezone.utc)))
    yield {'engine':engine,'authority':authority,'auth':auth,'service':service}
    engine.dispose()


def command(env,operation,payload,*,request_id=None,auth=None):
    auth=auth or env['auth']
    with env['engine'].connect() as conn: state=env['authority'].state(conn,auth,lock=False)
    return Command(schema_version=2,request_id=request_id or uuid4().hex,expected_version=state.business_seq,
        expected_workspace_revision=state.workspace_revision,operation=operation,payload=payload)


def do(env,operation,payload,**kw):
    return env['service'].execute(kw.get('auth') or env['auth'],command(env,operation,payload,**kw))


def product(env,**kw):
    return do(env,'work_products.create',{'kind':'text','title':'私人假设','purpose':'未知用途','content':'也许延期更合适',**kw})['object']


def edit_payload(p,**patch):
    return {**{k:p[k] for k in ['kind','title','purpose','content','structured_payload','evidence_refs','task','legacy']},
            'product_id':p['product_id'],'expected_head':p['version'],**patch}
