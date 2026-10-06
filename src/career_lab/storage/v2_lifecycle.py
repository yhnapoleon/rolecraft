"""Common lifecycle plans; business review/evaluation is provided by W05."""
from uuid import uuid4
from career_lab.contracts.v2 import *
from .v2_store import Mutation,ObjectWrite,EventDraft

def point(state):return VersionPoint(**state.model_dump(include={'business_seq','workspace_revision','storage_revision'}))
def objref(sid,kind,oid,version=1):return ObjectRef(session_id=sid,kind=kind,object_id=oid,version=version)

def begin_revision(view,cmd,auth):
    body=BeginRevisionInput.model_validate(cmd.payload)
    if cmd.operation!='begin_revision' or view.state.status!='submitted':raise ProtocolError('revision_not_available',status=409)
    parent=SubmissionV2.model_validate(view.get(body.parent_submission).content)
    if parent.cycle.object_id!=view.state.cycle_id:raise ProtocolError('revision_parent_not_current',status=409)
    oid=uuid4().hex;cycle=RevisionCycle(id=oid,session_id=auth.session_id,parent_submission=body.parent_submission,opened_at=point(view.state),base_state_ref=digest(view.state),reason=body.reason)
    ref=objref(auth.session_id,'cycle',oid)
    write=ObjectWrite(ref=ref,expected_head=0,content=cycle.model_dump(mode='json'),dependencies=(body.parent_submission,))
    return Mutation(writes=(write,),events=(EventDraft(type='revision_opened',visible_to=('learner',),refs=(ref,)),),state_changes={'status':'active','cycle_id':oid},result={'cycle':ref.model_dump(mode='json')})

def record_submission(view,cmd,auth):
    body=SubmitInput.model_validate(cmd.payload)
    current=view.current_cycle or max((x for x in view.objects if x.ref.kind=='cycle' and x.ref.object_id==view.state.cycle_id),key=lambda x:x.ref.version)
    cycle=RevisionCycle.model_validate(current.content)
    updated=RevisionCycle.model_validate(cycle.model_dump(mode='json')|{'version':cycle.version+1,'status':'submitted'})
    cycle_ref=objref(auth.session_id,'cycle',cycle.id,updated.version)
    oid=uuid4().hex
    sub=SubmissionV2(id=oid,session_id=auth.session_id,cycle=cycle_ref,decision=body.decision,products=body.products,config=body.config,evidence_refs=body.evidence_refs,as_of=point(view.state),scenario=view.bindings.scenario,evaluation=view.bindings.evaluation,executor=auth.executor)
    ref=objref(auth.session_id,'submission',oid)
    from .v2_store import references
    return Mutation(writes=(ObjectWrite(ref=cycle_ref,expected_head=cycle.version,content=updated.model_dump(mode='json'),dependencies=(cycle.parent_submission,) if cycle.parent_submission else ()),ObjectWrite(ref=ref,expected_head=0,content=sub.model_dump(mode='json'),dependencies=references(sub.model_dump(mode='json')))),events=(EventDraft(type='submitted',visible_to=('learner',),refs=(ref,)),),state_changes={'status':'submitted'},result={'submission':ref.model_dump(mode='json')})

def record_review(view,cmd,auth):
    body=ReviewInput.model_validate(cmd.payload);oid=uuid4().hex
    request=ReviewRequest(id=oid,session_id=auth.session_id,subjects=body.subjects,purpose=body.purpose,scope=body.scope,question=body.question,as_of=point(view.state),evaluation=view.bindings.evaluation,executor=auth.executor)
    ref=objref(auth.session_id,'review',oid)
    return Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=request.model_dump(mode='json'),dependencies=body.subjects),),result={'review':ref.model_dump(mode='json')})
