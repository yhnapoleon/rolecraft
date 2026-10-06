from pathlib import Path
import hashlib,json,sqlite3,shutil
import pytest
from pydantic import ValidationError
from sqlalchemy import delete
from career_lab.contracts.versioning import decode,digest_v1,preserve_legacy_annotation
from career_lab.contracts.actions import Action
from career_lab.contracts.v2 import Command,ProtocolError,digest
from career_lab.storage.sessions import SessionStore
from career_lab.storage.database import objects,object_times,object_metadata
from career_lab.storage.v2_store import V2Store
from career_lab.api.feedback import generate_feedback
from career_lab.rubrics.registry import RulesRegistry
from career_lab.contracts.v2.legacy import normalize_legacy_product,restore_legacy_product
F=Path(__file__).parent/'fixtures/v1'

def read(name):return json.loads((F/name).read_text())

def test_fixed_v1_bytes_hashes_defaults_and_decoder():
    manifest=read('provenance.json')
    for name,expected in manifest['files'].items():assert hashlib.sha256((F/name).read_bytes()).hexdigest()==expected
    for name,file in [('Action','action.json'),('Event','event.json'),('WorldState','world-initial.json'),('ScenarioSpec','scenario.json'),('EvidencePackage','evidence.json')]:
        raw=read(file);assert decode(name,raw).model_dump(mode='json')==raw
        with pytest.raises(ValidationError):decode(name,raw|{'new_default':None})
    a=read('action.json');assert digest_v1({'action':a,'object':None})==read('action-request-hash.json')['sha256']
    cmd=dict(schema_version=2,request_id='k',expected_version=0,expected_workspace_revision=0,operation='save')
    assert digest(Command(**cmd))==digest(Command(**cmd,payload={}))
    assert digest({'value':None})!=digest({}) and digest({'value':[]})!=digest({'value':None})
    with pytest.raises(ProtocolError):decode('Action',a|{'schema_version':1})


def test_old_database_columns_rows_hashes_and_pending_feedback(tmp_path):
    db=tmp_path/'old.sqlite3';shutil.copyfile(F/'legacy.sqlite3',db)
    def dump():
        with sqlite3.connect(db) as conn:
            tables=[x[0] for x in conn.execute("select name from sqlite_master where type='table' order by name")]
            return {t:{'cols':conn.execute(f'pragma table_info("{t}")').fetchall(),'rows':conn.execute(f'select * from "{t}"').fetchall()} for t in tables if not t.startswith('v2_')}
    before=dump();v2=V2Store('sqlite:///'+str(db));v2.db.engine.dispose();after=dump()
    assert {table:after[table] for table in before}==before
    assert set(after)-set(before)<= {'jobs'} # Base metadata may create the existing jobs table when first opened by the API.
    store=SessionStore('sqlite:///'+str(db));a=Action.model_validate(read('action.json'))
    assert store.commit_action('w00-compat-v1',a).replayed
    sub=read('submission.json');assert generate_feedback(store,'w00-compat-v1',sub['id'])==read('feedback.json')
    with store.db.transaction() as c:
        from career_lab.api.feedback import feedback_id
        fid=feedback_id(store,'w00-compat-v1',sub['id'])
        c.execute(delete(objects).where(objects.c.id==fid))
        c.execute(delete(object_times).where(object_times.c.id==fid))
        c.execute(delete(object_metadata).where(object_metadata.c.id==fid))
    assert generate_feedback(store,'w00-compat-v1',sub['id'])==read('feedback.json')
    # A real legacy write still works in a new legacy session beside v2 tables.
    state=store.create_session(decode('ScenarioSpec',read('scenario.json')),'legacy-new')
    assert store.commit_action(state.session_id,a).state.version==1
    store.close()


def test_rules_registry_does_not_alias_v4_or_unavailable_history():
    registry=RulesRegistry();item=decode('EvidencePackage',read('evidence.json'))
    assert registry.get('rules-v3')(item)[0].criterion_id=='R3.capacity'
    with pytest.raises(ProtocolError):registry.get('rules-v2')
    with pytest.raises(ProtocolError):registry.get('rules-v4')
    # An independently installed v4 engine is routed by exact revision; it is not v4 product semantics.
    def independent_engine(value):return ('v4-extension',value)
    registry.register('rules-v4',independent_engine)
    assert registry.get('rules-v4')('synthetic-input')==('v4-extension','synthetic-input')
    assert registry.get('rules-v3')(item)[0].criterion_id=='R3.capacity'
    with pytest.raises(ValueError):registry.register('rules-v3',independent_engine)

@pytest.mark.parametrize('raw',[
 {'id':'text','kind':'text','purpose':'自由作品','body':'保留正文','draft':{'body':'未保存'},'removedAt':None,'adopted':False,'unknown_future':{'x':1}},
 {'id':'tests','kind':'test_set','purpose':'测试计划','cases':[{'id':'case1','question':'政策？','expectation':'待核验','pending':True}],'returnId':'return1','requestId':'local1'},
 {'id':'investigation','kind':'investigation','purpose':'探索笔记','blocks':[{'type':'test_compare','testIds':['old-test']}],'review':{'direction':'unknown','note':'保留判断'},'removedAt':'2026-10-06T00:00:00Z'},
])
def test_lossless_legacy_product_mapping(raw):
    imported=normalize_legacy_product(raw,'old-session')
    assert restore_legacy_product(imported)==raw
    assert imported.kind==('test_plan' if raw['kind']=='test_set' else raw['kind'])
    assert imported.run_verification=='unverified_local' and not imported.execute_pending
    with pytest.raises(ValueError):normalize_legacy_product(raw|{'token':'never-import'},'old-session')


def test_legacy_g1_not_upgraded_to_two_humans():
    original={'item_id':'legacy','label':'SUPPORTED','label_tier':'G1','acceptable_evidence_sets':[['e1']],'annotation_version':'source-corpus'}
    migrated=preserve_legacy_annotation(original)
    assert migrated.original==original and migrated.original_tier=='G1' and migrated.eligible_as_new_g1 is False
