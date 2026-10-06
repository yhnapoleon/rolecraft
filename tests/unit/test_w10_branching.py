"""W10 real mapping/repository tests against explicit synthetic snapshots."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from career_lab.contracts.v2 import (
    ActionBoundary, ActionProposal, AssistantConfig, AuthContext, BusinessDecision,
    EffectiveConfig, EvidenceRefV2, Executor, FeedbackV2, FileRef, Lineage, ObjectRef,
    ProductShare, RestoreResult, RevisionCycle, RunManifest, SessionBindings,
    SnapshotExport, SourceIdentity, StoredEvent, StoredObject, SubmissionV2,
    TestResultV2 as Result, VersionPoint, WorkProductVersion, WorldStateV2, Budget,
    ProtocolError, canonical, digest,
)
from career_lab.branching.mapping import DEFAULT_OBJECT_CODECS, EventCodec, validate_prefix, make_plan, remap_snapshot, ref_key
from career_lab.branching.prefix import compare_prefix, prefix_value
from career_lab.branching.repository import BranchRepository
from career_lab.branching.service import BranchService

H = "a"*64
F = FileRef(path="fixture.json", sha256=H)
ACTOR = Executor(id="learner", kind="human")
P = VersionPoint(business_seq=2, workspace_revision=1, storage_revision=3)
EVENTS = {"product_saved": EventCodec(reference_fields=("product",), literal_fields=("note",)),
          "test_recorded": EventCodec(reference_fields=("test",))}
ACTION = ActionProposal(id="change", tool="read_material", arguments={}, purpose="inspect alternative")


def ref(kind, oid, version=1, config=None):
    return ObjectRef(session_id="parent", kind=kind, object_id=oid, version=version, config_version=config)


def seal(s):
    data = s.model_dump(mode="json", exclude={"snapshot_hash"})
    return SnapshotExport.model_validate({**data, "snapshot_hash": digest(data)})


def snapshot():
    c, p, cfg, sub = ref("cycle","cycle"), ref("work_product","product"), ref("config","config",config=0), ref("submission","submission")
    doc = EvidenceRefV2(session_id="parent",kind="document",object_id="faq",version=1,observed_at_seq=0)
    cycle = RevisionCycle(id="cycle",session_id="parent",opened_at=VersionPoint(business_seq=0,workspace_revision=0,storage_revision=0),base_state_ref="parent-snapshot")
    product = WorkProductVersion(product_id="product",session_id="parent",version=1,cycle=c,
        content="literal product and parent IDs stay text",author=ACTOR,executor=ACTOR,
        evidence_refs=(doc,),content_hash=digest({"content":"literal product and parent IDs stay text","structured_payload":None}),
        created_at=datetime(2026,10,6,tzinfo=timezone.utc))
    share = ProductShare(id="share",session_id="parent",version=1,product=p,recipient_role="tech",shared_at=P)
    config = AssistantConfig(id="config",session_id="parent",domains=("faq",))
    test = Result(id="test",session_id="parent",query="q",config=EffectiveConfig(requested=config,effective=config),
                  status="fallback",answer="human",citations=(doc,),as_of=P)
    submission = SubmissionV2(id="submission",session_id="parent",cycle=c,decision="no_go",
        products=(p,),config=cfg,evidence_refs=(doc,),as_of=P,scenario=F,evaluation=F,executor=ACTOR)
    feedback = FeedbackV2(id="feedback",session_id="parent",subject=sub,evaluation=F,as_of=P,items=(),
                         business_response="fixture only",next_options=(),verified_coverage=0,model_coverage=0)
    values = [(c,cycle,0),(cfg,config,0),(p,product,1),(ref("share","share"),share,3),
              (ref("test","test"),test,3),(sub,submission,3),(ref("feedback","feedback"),feedback,3)]
    objects = tuple(StoredObject(ref=r,content=m.model_dump(mode="json"),visible_to=("learner","tech"),created_storage_revision=rev) for r,m,rev in values)
    boundaries = (ActionBoundary(transaction_id="tx1",request_id="request1",start_seq=0,end_seq=1,storage_revision=1),
                  ActionBoundary(transaction_id="tx2",request_id="request2",start_seq=1,end_seq=2,storage_revision=3))
    events = (StoredEvent(id="event1",session_id="parent",seq=1,transaction_id="tx1",type="product_saved",executor=ACTOR,
                         visible_to=("learner",),refs=(p,),data={"product":p.model_dump(mode="json"),"note":"parent product"}),
              StoredEvent(id="event2",session_id="parent",seq=2,transaction_id="tx2",type="test_recorded",executor=ACTOR,
                         visible_to=("learner",),refs=(ref("test","test"),),data={"test":ref("test","test").model_dump(mode="json")}))
    value = SnapshotExport.model_construct(id="parent-snapshot",session_id="parent",bindings=SessionBindings(scenario=F,runtime=F,evaluation=F),
        state=WorldStateV2(session_id="parent",cycle_id="cycle",resources={"capacity":30},**P.model_dump(exclude={"schema_version"})),
        objects=objects,events=events,boundaries=boundaries,source_digest=H,snapshot_hash=H)
    return seal(value), (doc,)


def auth(**changes):
    return AuthContext(session_id="parent",actor_id="learner",executor=ACTOR,capabilities=("read","research"),credential_id="research-key").model_copy(update=changes)


def parent_file(root):
    m = RunManifest(id="parent-run",session_id="parent",executor=ACTOR,scenario=F,runtime=F,evaluation=F,
        seed=3,split="dev",budget=Budget(model_calls=0,actions=10,wall_seconds=60),provider="fixture",model_revision="fixture",
        source=SourceIdentity(base_commit="8"*40,source_digest=H),
        lineage=Lineage(structure_id="structure",component_id="component",run_id="parent-run",session_id="parent"))
    raw=(canonical(m)+"\n").encode();(root/"parent.json").write_bytes(raw)
    return FileRef(path="parent.json",sha256=hashlib.sha256(raw).hexdigest())


def prepare(service, root, **changes):
    s, external = snapshot()
    args=dict(parent_ref=parent_file(root),parent_root=root,snapshot=s,request_id="fork",intervention=ACTION,continuation_runtime=F,external_refs=external)
    args.update(changes)
    return service.prepare(auth(),**args)


def test_full_typed_mapping_covers_product_share_cycle_test_submission_feedback():
    s,external=snapshot(); before=s.model_dump_json()
    checked,order=validate_prefix(s,DEFAULT_OBJECT_CODECS,EVENTS,external)
    plan=make_plan(checked,"child","branch",external)
    child=remap_snapshot(checked,plan,DEFAULT_OBJECT_CODECS,EVENTS,order)
    validate_prefix(child,DEFAULT_OBJECT_CODECS,EVENTS,tuple(plan.reference(r) for r in external))
    assert s.model_dump_json()==before
    assert all(o.ref.session_id=="child" and o.ref.object_id!=s.objects[i].ref.object_id for i,o in enumerate(child.objects))
    by_kind={o.ref.kind:o.content for o in child.objects}
    assert by_kind["share"]["product"]["session_id"]=="child"
    assert by_kind["work_product"]["cycle"]["object_id"]==child.state.cycle_id
    assert by_kind["test"]["config"]["requested"]["session_id"]=="child"
    assert by_kind["test"]["config"]["effective"]["id"]==by_kind["config"]["id"]
    assert by_kind["feedback"]["subject"]["object_id"]==by_kind["submission"]["id"]
    assert by_kind["work_product"]["content"]=="literal product and parent IDs stay text"
    assert child.events[0].data["note"]=="parent product"
    assert child.events[0].data["product"]["object_id"]==by_kind["work_product"]["product_id"]
    assert child.boundaries[0].request_id!="request1"
    assert compare_prefix(child,child)["equal"]


@pytest.mark.parametrize("fault",["future_object","dangling","cycle","unknown_event","unknown_field","mid_boundary","missing_event"])
def test_invalid_prefix_refuses_approximate_reconstruction(fault):
    s,ext=snapshot()
    if fault=="future_object":
        objs=list(s.objects);objs[-1]=objs[-1].model_copy(update={"created_storage_revision":4});s=s.model_copy(update={"objects":tuple(objs)})
    elif fault=="dangling":
        s=s.model_copy(update={"objects":s.objects[:-1]});event=s.events[0].model_copy(update={"refs":(ref("feedback","feedback"),)});s=s.model_copy(update={"events":(event,s.events[1])})
    elif fault=="cycle":
        objs=list(s.objects);objs[0]=objs[0].model_copy(update={"dependencies":(objs[2].ref,)});s=s.model_copy(update={"objects":tuple(objs)})
    elif fault=="unknown_event":
        s=s.model_copy(update={"events":(s.events[0].model_copy(update={"type":"unsupported"}),s.events[1])})
    elif fault=="unknown_field":
        s=s.model_copy(update={"events":(s.events[0].model_copy(update={"data":{"unknown_id":"parent"}}),s.events[1])})
    elif fault=="mid_boundary":
        s=s.model_copy(update={"state":s.state.model_copy(update={"storage_revision":2})})
    else:s=s.model_copy(update={"events":s.events[:1]})
    with pytest.raises(ProtocolError):
        validate_prefix(seal(s),DEFAULT_OBJECT_CODECS,EVENTS,ext)


def test_business_value_and_version_changes_remain_in_prefix_diff():
    s,_=snapshot()
    changed=seal(s.model_copy(update={"state":s.state.model_copy(update={"resources":{"capacity":60}})}))
    compared=compare_prefix(s,changed)
    assert not compared["equal"]
    assert any(x["path"]=="/state/resources/capacity" for x in compared["differences"])


def test_sqlite_idempotency_and_reopen(tmp_path):
    repo=BranchRepository(tmp_path/"branch.db");svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS)
    first=prepare(svc,tmp_path);again=prepare(svc,tmp_path)
    assert first==again and first["status"]=="prepared"
    assert not first["preparation"]["effects_executed"]
    reloaded=BranchRepository(tmp_path/"branch.db").get(auth(),first["id"])
    assert reloaded==first
    with pytest.raises(ProtocolError,match="conflict"):
        prepare(svc,tmp_path,intervention=ACTION.model_copy(update={"purpose":"changed"}))


def test_concurrent_same_request_has_one_branch(tmp_path):
    repo=BranchRepository(tmp_path/"concurrent.db");svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS)
    pref=parent_file(tmp_path);s,ext=snapshot()
    def call(_):
        try:
            return svc.prepare(auth(),parent_ref=pref,parent_root=tmp_path,snapshot=s,request_id="fork",intervention=ACTION,continuation_runtime=F,external_refs=ext)
        except ProtocolError as exc:
            assert exc.code == "branch_operation_in_progress"
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(call,range(8)))
    successful = [r for r in results if r is not None]
    assert successful and len({r["id"] for r in successful})==1
    assert repo.get(auth(),successful[0]["id"])["status"]=="prepared"
    assert call(0)["id"] == successful[0]["id"]


@pytest.mark.parametrize("changes",[{"session_id":"other"},{"capabilities":("read",)},{"expires_at":datetime.now(timezone.utc)-timedelta(days=1)},{"allowed_objects":("subset",)}])
def test_research_access_checked_before_branch_data(tmp_path,changes):
    repo=BranchRepository(tmp_path/"auth.db");svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS);row=prepare(svc,tmp_path)
    with pytest.raises(ProtocolError):
        repo.get(auth(**changes),row["id"])


def test_invalid_prefix_records_failure(tmp_path):
    repo=BranchRepository(tmp_path/"failure.db");svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS)
    s,_=snapshot();s=seal(s.model_copy(update={"events":()}))
    with pytest.raises(ProtocolError):prepare(svc,tmp_path,snapshot=s)
    assert repo.failures(auth())[0]["code"]=="event_sequence_incomplete"


class RestoreDouble:
    def __init__(self, fault=None):
        self.fault=fault;self.parent=H;self.child=None;self.calls=0
    def parent_digest(self,sid):return self.parent
    def restore(self,prepared,request_id):
        self.calls+=1;self.child=prepared
        if self.fault=="parent":self.parent="b"*64
        if self.fault=="content":
            obj=prepared.objects[0].model_copy(update={"visible_to":("hidden",)})
            self.child=seal(prepared.model_copy(update={"objects":(obj,*prepared.objects[1:])}))
        return RestoreResult(session_id=prepared.session_id,source_snapshot_hash=prepared.snapshot_hash,id_map={},state=prepared.state,prefix_digest=digest(prefix_value(self.child)))
    def read_child(self,sid):return self.child


def test_restore_port_verification_and_replay_does_not_reinvoke(tmp_path):
    repo=BranchRepository(tmp_path/"restore.db");svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS);row=prepare(svc,tmp_path)
    port=RestoreDouble();done=svc.restore(auth(),row["id"],port)
    assert done["status"]=="restored" and port.calls==1
    assert svc.restore(auth(),row["id"],port)==done and port.calls==1
    assert not done["restore"]["intervention_executed"]


@pytest.mark.parametrize("fault",["parent","content"])
def test_bad_restore_never_marked_restored(tmp_path,fault):
    repo=BranchRepository(tmp_path/"bad.db");svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS);row=prepare(svc,tmp_path)
    with pytest.raises(ProtocolError):svc.restore(auth(),row["id"],RestoreDouble(fault))
    assert repo.get(auth(),row["id"])["status"]=="failed"
    assert repo.failures(auth())


def test_parent_file_hash_drift_prevents_prepare(tmp_path):
    repo=BranchRepository(tmp_path/"drift.db");svc=BranchService(repo,DEFAULT_OBJECT_CODECS,EVENTS);pref=parent_file(tmp_path)
    (tmp_path/"parent.json").write_text("{}");s,ext=snapshot()
    with pytest.raises(ProtocolError,match="hash"):
        svc.prepare(auth(),parent_ref=pref,parent_root=tmp_path,snapshot=s,request_id="fork",intervention=ACTION,continuation_runtime=F,external_refs=ext)


def test_unrelated_database_is_not_used(tmp_path):
    import sqlite3
    with sqlite3.connect(tmp_path/"existing.db") as c:c.execute("CREATE TABLE product_data(id INTEGER)")
    with pytest.raises(ProtocolError,match="unrelated database"):
        BranchRepository(tmp_path/"existing.db")


def test_rejected_business_decision_is_mapped_as_history_not_applied():
    from career_lab.contracts.v2 import BusinessRequest
    s,ext=snapshot();point=VersionPoint(business_seq=1,workspace_revision=1,storage_revision=2)
    request=BusinessRequest(id='business-request',session_id='parent',version=1,requested={'capacity':60},
        reason='exploration',status='rejected',as_of=point,executor=ACTOR)
    request_ref=ref('business_request','business-request')
    decision=BusinessDecision(id='denial',session_id='parent',version=1,request=request_ref,status='rejected',
        decider='supervisor',rule_revision='rules-v4',reason_code='over_limit',reason='not granted',as_of=point)
    objects=(*s.objects,StoredObject(ref=request_ref,content=request.model_dump(mode='json'),visible_to=('learner',),created_storage_revision=2),
             StoredObject(ref=ref('business_decision','denial'),content=decision.model_dump(mode='json'),visible_to=('learner',),created_storage_revision=2))
    s=seal(s.model_copy(update={'objects':objects}));checked,order=validate_prefix(s,DEFAULT_OBJECT_CODECS,EVENTS,ext)
    plan=make_plan(checked,'child','branch',ext);child=remap_snapshot(checked,plan,DEFAULT_OBJECT_CODECS,EVENTS,order)
    denial=next(o.content for o in child.objects if o.ref.kind=='business_decision')
    assert denial['status']=='rejected' and denial['granted']=={}
    assert denial['request']['session_id']=='child' and denial['request']['object_id']!='business-request'
    assert child.state.resources==s.state.resources=={'capacity':30}
