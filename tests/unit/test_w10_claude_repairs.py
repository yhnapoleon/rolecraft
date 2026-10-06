"""Existing review defects only; research extension remains deferred."""
import sqlite3
import pytest
from career_lab.contracts.v2 import ProtocolError,WorkProductVersion,EvidenceRefV2
from career_lab.branching.repository import BranchRepository
from career_lab.branching.service import BranchService
from career_lab.branching.mapping import validate_prefix,make_plan,remap_snapshot
from career_lab.branching.w01_bridge import verify_model_literals
from career_lab.diagnostics.v2.events import DiagnosticEvent,VersionChange,diagnose
from test_w10_branching import snapshot,prepare,auth,seal,DEFAULT_OBJECT_CODECS,EVENTS


def test_transient_prepare_error_keeps_same_request_recoverable(tmp_path):
    class Once(BranchRepository):
        def __init__(self,path):super().__init__(path);self.fail_once=True
        def prepared(self,*args):
            if self.fail_once:self.fail_once=False;raise sqlite3.OperationalError('synthetic temporary storage failure')
            return super().prepared(*args)
    repo=Once(tmp_path/'state.db');svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS)
    with pytest.raises(sqlite3.OperationalError):prepare(svc,tmp_path)
    with sqlite3.connect(tmp_path/'state.db') as conn:before=conn.execute('select id,status from w10_branches').fetchone()
    assert before[1]=='preparing'
    done=prepare(svc,tmp_path);assert done['status']=='prepared' and done['id']==before[0]
    assert repo.failures(auth())[0]['code']=='OperationalError'


def test_opaque_cycle_anchor_is_preserved_not_guessed_as_an_object_ref():
    s,ext=snapshot();objects=[]
    for o in s.objects:
        if o.ref.kind=='cycle':o=o.model_copy(update={'content':{**o.content,'base_state_ref':'initial:historical-parent'}})
        objects.append(o)
    s=seal(s.model_copy(update={'objects':tuple(objects)}));s,order=validate_prefix(s,DEFAULT_OBJECT_CODECS,EVENTS,ext)
    plan=make_plan(s,'child','branch',ext);child=remap_snapshot(s,plan,DEFAULT_OBJECT_CODECS,EVENTS,order)
    assert next(o for o in child.objects if o.ref.kind=='cycle').content['base_state_ref']=='initial:historical-parent'


def test_independent_business_literal_check_detects_changed_content():
    s,ext=snapshot();s,order=validate_prefix(s,DEFAULT_OBJECT_CODECS,EVENTS,ext);plan=make_plan(s,'child','branch',ext)
    child=remap_snapshot(s,plan,DEFAULT_OBJECT_CODECS,EVENTS,order)
    original=next(o for o in s.objects if o.ref.kind=='work_product');mapped=next(o for o in child.objects if o.ref.kind=='work_product')
    a=WorkProductVersion.model_validate(original.content);b=WorkProductVersion.model_validate(mapped.content)
    verify_model_literals(a,b,plan.ids,'parent','child',entity_ref=original.ref)
    with pytest.raises(ProtocolError):verify_model_literals(a,b.model_copy(update={'content':'tampered'}),plan.ids,'parent','child',entity_ref=original.ref)


def test_two_old_references_produce_distinct_finding_ids():
    def ref(oid,version,seq):return EvidenceRefV2(session_id='s',kind='document',object_id=oid,version=version,observed_at_seq=seq)
    event=DiagnosticEvent(id='event',seq=3,session_id='s',actor_id='learner',operation='read_material',visible_to=('learner',),outcome='success',evidence=(ref('a',1,1),ref('b',1,1)))
    changes=[VersionChange(object_id=x,kind='document',version=2,seq=2,source=ref(x,2,2),visible_to=('learner',)) for x in ['a','b']]
    rows=diagnose([event],session_id='s',viewer_id='learner',changes=changes)
    assert len(rows)==2 and len({r.id for r in rows})==2
