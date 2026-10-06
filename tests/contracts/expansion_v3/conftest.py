from datetime import datetime,timezone
import pytest
from career_lab.contracts.v2 import *
from career_lab.storage.v2_store import *
from career_lab.api.modules import *

@pytest.fixture
def foundation(tmp_path):
    import os
    pg=os.getenv('ROLECRAFT_W01_TEST_PG')
    if pg:
        import psycopg
        from psycopg import sql
        from uuid import uuid4
        from urllib.parse import quote
        schema='w01_'+uuid4().hex
        with psycopg.connect(pg.replace('postgresql+psycopg://','postgresql://'),autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        url=pg+'?options='+quote('-csearch_path='+schema)
    else:url='sqlite:///'+str(tmp_path/'v2.db')
    store=V2Store(url)
    ref=FileRef(path='bundles/frozen.json',sha256=digest({}))
    bindings=SessionBindings(scenario=ref,runtime=ref,evaluation=ref)
    config=AssistantConfig(id='c0',session_id='template',domains=('faq',))
    state,token=store.create_session(bindings,config,{'capacity':30,'dev_days':3})
    auth=store.authenticate(state.session_id,token)
    yield store,auth,token,bindings,config
    store.db.engine.dispose()

def command(view,key='one',operation='save'):
    state=view.state
    return Command(schema_version=2,request_id=key,expected_version=state.business_seq,expected_workspace_revision=state.workspace_revision,operation=operation)

def product_plan(view,cmd,auth,oid='product',expected_head=0):
    content='draft with an uncertain claim'
    cycle=next(x.ref for x in view.objects if x.ref.kind=='cycle' and x.ref.object_id==view.state.cycle_id)
    product=WorkProductVersion(product_id=oid,session_id=auth.session_id,version=expected_head+1,cycle=cycle,content=content,author=auth.executor,executor=auth.executor,content_hash=digest({'content':content,'structured_payload':None}),created_at=datetime.now(timezone.utc))
    ref=ObjectRef(session_id=auth.session_id,kind='product',object_id=oid,version=product.version)
    return Mutation(writes=(ObjectWrite(ref=ref,expected_head=expected_head,content=product.model_dump(mode='json'),dependencies=(cycle,)),),result={'ref':ref.model_dump(mode='json')})
