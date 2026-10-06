"""031 W10 F1-F3 regressions: synthetic DTOs, real processes/locks/SQLite."""
import os
import sys
import subprocess
import threading
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from career_lab.contracts.v2 import VersionPoint, ProtocolError
from career_lab.branching.repository import BranchRepository
from career_lab.branching.service import BranchService
from test_w10_branching import snapshot, seal, prepare, auth, RestoreDouble, DEFAULT_OBJECT_CODECS, EVENTS
from career_lab.branching.mapping import validate_prefix


@pytest.mark.parametrize('kind,field', [('cycle','opened_at'),('share','shared_at'),('share','revoked_at'),('test','as_of'),('submission','as_of'),('feedback','as_of')])
@pytest.mark.parametrize('dimension', ['business_seq','workspace_revision','storage_revision'])
def test_f1_each_internal_version_dimension_must_be_within_fork(kind,field,dimension):
    s,ext=snapshot();objects=[]
    for obj in s.objects:
        if obj.ref.kind==kind:
            content=dict(obj.content);point=dict(content.get(field) or {'schema_version':2,'business_seq':2,'workspace_revision':1,'storage_revision':3});point[dimension]=99;content[field]=point;obj=obj.model_copy(update={'content':content})
        objects.append(obj)
    with pytest.raises((ProtocolError,ValueError)):
        validate_prefix(seal(s.model_copy(update={'objects':tuple(objects)})),DEFAULT_OBJECT_CODECS,EVENTS,ext)


def test_f1_evidence_cannot_postdate_immutable_product_creation():
    s,ext=snapshot();objects=[]
    for obj in s.objects:
        if obj.ref.kind=='work_product':
            content=dict(obj.content);content['evidence_refs']=[{**content['evidence_refs'][0],'observed_at_seq':2}];obj=obj.model_copy(update={'content':content})
        objects.append(obj)
    with pytest.raises(ProtocolError) as err:
        validate_prefix(seal(s.model_copy(update={'objects':tuple(objects)})),DEFAULT_OBJECT_CODECS,EVENTS,ext)
    assert err.value.code=='future_evidence_reference'


def test_f1_evidence_uses_subject_as_of_not_only_fork():
    s,ext=snapshot();objects=[]
    for obj in s.objects:
        if obj.ref.kind=='test':
            content=dict(obj.content);content['as_of']={'schema_version':2,'business_seq':1,'workspace_revision':1,'storage_revision':1};content['citations']=[{**content['citations'][0],'observed_at_seq':2}];obj=obj.model_copy(update={'content':content})
        objects.append(obj)
    with pytest.raises(ProtocolError):validate_prefix(seal(s.model_copy(update={'objects':tuple(objects)})),DEFAULT_OBJECT_CODECS,EVENTS,ext)


def test_f2_dead_process_preparation_resumes_same_branch(tmp_path):
    code='''import os,sys
from pathlib import Path
sys.path.insert(0,str(Path('tests/unit').resolve()))
from test_w10_branching import prepare,DEFAULT_OBJECT_CODECS,EVENTS
from career_lab.branching.repository import BranchRepository
from career_lab.branching.service import BranchService
class Crash(BranchRepository):
 def prepared(self,*args,**kwargs):os._exit(81)
root=Path(sys.argv[1]);prepare(BranchService(Crash(root/'db.sqlite'),DEFAULT_OBJECT_CODECS,EVENTS),root)
'''
    process=subprocess.run([sys.executable,'-c',code,str(tmp_path)],cwd=Path(__file__).resolve().parents[2],timeout=15)
    assert process.returncode==81
    with sqlite3.connect(tmp_path/'db.sqlite') as conn:original=conn.execute('select id,status from w10_branches').fetchone()
    assert original[1]=='preparing'
    repo=BranchRepository(tmp_path/'db.sqlite');svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS)
    records=[prepare(svc,tmp_path) for _ in range(3)]
    assert all(r['id']==original[0] and r['status']=='prepared' for r in records)
    assert svc.restore(auth(),original[0],RestoreDouble())['status']=='restored'


def test_f2_active_preparer_is_not_taken_over(tmp_path):
    entered,release=threading.Event(),threading.Event()
    class Held(BranchRepository):
        def prepared(self,*args,**kwargs):
            entered.set();assert release.wait(5)
            return super().prepared(*args,**kwargs)
    svc=BranchService(Held(tmp_path/'active.sqlite'),DEFAULT_OBJECT_CODECS,EVENTS)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(prepare,svc,tmp_path)
        assert entered.wait(5)
        try:
            with pytest.raises(ProtocolError) as err:prepare(svc,tmp_path)
            assert err.value.code=='branch_operation_in_progress'
        finally:release.set()
        assert future.result(timeout=5)['status']=='prepared'


class LostReply(RestoreDouble):
    idempotent_restore=True
    def __init__(self):
        super().__init__();self.results={};self.writes=0;self.lookups=0
    def restore(self,prepared,request_id):
        if request_id in self.results:return self.results[request_id]
        result=super().restore(prepared,request_id);self.writes+=1;self.results[request_id]=result
        raise TimeoutError('response lost after durable result')
    def lookup_restore(self,request_id):
        self.lookups+=1
        return self.results.get(request_id)


def test_f3_lost_reply_is_read_only_reconciled_with_history(tmp_path):
    repo=BranchRepository(tmp_path/'lost.sqlite');svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS);row=prepare(svc,tmp_path);port=LostReply()
    with pytest.raises(TimeoutError):svc.restore(auth(),row['id'],port)
    assert repo.get(auth(),row['id'])['status']=='unresolved'
    done=svc.restore(auth(),row['id'],port)
    assert done['status']=='restored' and port.writes==1 and port.calls==1 and port.lookups==1
    assert repo.failures(auth())[0]['code']=='TimeoutError'


def test_f3_active_restore_cannot_be_stolen_and_late_error_cannot_poison(tmp_path):
    entered,release=threading.Event(),threading.Event()
    class HeldLoss(LostReply):
        def restore(self,*args):
            try:return super().restore(*args)
            except TimeoutError:
                entered.set();assert release.wait(5);raise
    repo=BranchRepository(tmp_path/'race.sqlite');svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS);row=prepare(svc,tmp_path);port=HeldLoss()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(svc.restore,auth(),row['id'],port);assert entered.wait(5)
        try:
            with pytest.raises(ProtocolError) as err:svc.restore(auth(),row['id'],port)
            assert err.value.code=='branch_operation_in_progress'
        finally:release.set()
        with pytest.raises(TimeoutError):future.result(timeout=5)
    done=svc.restore(auth(),row['id'],port);assert done['status']=='restored' and port.writes==1
    assert repo.finish_restore(auth(),row['id'],'old-token','unresolved',error_code='late_timeout')==done


def test_f3_stale_claim_cannot_commit(tmp_path):
    repo=BranchRepository(tmp_path/'claim.sqlite');svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS);row=prepare(svc,tmp_path)
    _,first=repo.claim_restore(auth(),row['id'],'parent-digest');_,second=repo.claim_restore(auth(),row['id'],'parent-digest')
    with pytest.raises(ProtocolError) as err:repo.finish_restore(auth(),row['id'],first,'unresolved',error_code='late')
    assert err.value.code=='restore_claim_lost'
    result=repo.finish_restore(auth(),row['id'],second,'unresolved',error_code='current')
    assert result['error_code']=='current'


def test_f3_process_death_after_child_commit_recovers_saved_result(tmp_path):
    repo=BranchRepository(tmp_path/'process.sqlite');svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS);row=prepare(svc,tmp_path)
    code='''import os,sys
from pathlib import Path
sys.path.insert(0,str(Path('tests/unit').resolve()))
from test_w10_branching import RestoreDouble,auth,DEFAULT_OBJECT_CODECS,EVENTS
from career_lab.branching.repository import BranchRepository
from career_lab.branching.service import BranchService
root=Path(sys.argv[1])
class Crash(RestoreDouble):
 def restore(self,prepared,request_id):
  result=super().restore(prepared,request_id)
  (root/'child.json').write_text(self.child.model_dump_json())
  (root/'result.json').write_text(result.model_dump_json())
  (root/'request.txt').write_text(request_id)
  os._exit(82)
BranchService(BranchRepository(root/'process.sqlite'),DEFAULT_OBJECT_CODECS,EVENTS).restore(auth(),sys.argv[2],Crash())
'''
    process=subprocess.run([sys.executable,'-c',code,str(tmp_path),row['id']],cwd=Path(__file__).resolve().parents[2],timeout=15)
    assert process.returncode==82 and repo.get(auth(),row['id'])['status']=='restoring'
    from career_lab.contracts.v2 import RestoreResult,SnapshotExport
    class LookupOnly:
        def parent_digest(self,sid):return 'a'*64
        def lookup_restore(self,rid):
            assert rid==(tmp_path/'request.txt').read_text()
            return RestoreResult.model_validate_json((tmp_path/'result.json').read_text())
        def read_child(self,sid):return SnapshotExport.model_validate_json((tmp_path/'child.json').read_text())
        def restore(self,*args):raise AssertionError('must not repeat effect')
    done=svc.restore(auth(),row['id'],LookupOnly())
    assert done['status']=='restored' and done['restore']['attempt']==2
