"""Small shared W07/W08 contract slice; no training, models or source fabrication."""
from pathlib import Path
import json
import pytest
from pydantic import ValidationError
from career_lab.contracts import v2 as C
from career_lab.contracts.v2.data import model_input,metadata_projection,validate_record_annotation

DRAFT=Path(__file__).resolve().parents[3]/'docs/contracts/expansion-v3/drafts/draft-20261006-2020/examples'

def record(family='relation',*,known=True,until=20,reference=5):
    raw=json.loads((DRAFT/f'DatasetRecordV2-{family}.json').read_text());raw['bucket']='fixture'
    if family in {'relation','criterion'}:
        evidence=raw['model_input']['evidence'];evidence['as_of']={'schema_version':2,'business_seq':reference,'workspace_revision':reference,'storage_revision':reference}
        if not evidence['candidate_evidence']:
            evidence['candidate_evidence']=[{'schema_version':2,'id':'e1','text':'Synthetic historical policy','ref':{'schema_version':2,'session_id':raw['lineage'].get('session_id') or 'fixture','kind':'material','object_id':'policy','version':1,'config_version':None,'observed_at_seq':0,'valid_from_seq':0,'valid_until_seq':until,'quote':None,'span_start':None,'span_end':None}}]
        for candidate in evidence['candidate_evidence']:
            candidate['ref']['observed_at_seq']=0;candidate['ref']['valid_from_seq']=0;candidate['ref']['valid_until_seq']=until
        evidence['rule_context']['evidence_time_context']={'policy':'historical-evidence-time-v1','status':'known' if known else 'undetermined','reference_seq':reference,'validity_known_ids':[c['id'] for c in evidence['candidate_evidence']] if known else []}
        evidence['input_hash']=C.digest({k:v for k,v in evidence.items() if k!='input_hash'})
    raw['input_hash']=C.digest(raw['model_input']);return C.DatasetRecordV2.model_validate(raw)

def accepted(r):
    candidate=r.model_input.evidence.candidate_evidence[0].id
    decision=C.AnnotationDecision(task_type=r.model_input.task_type,label='SUPPORTED' if r.family=='relation' else 'MET',applicability='applicable',evidence_ids=(candidate,),acceptable_evidence_sets=((candidate,),),evidence_evaluable=True)
    attempt=C.AnnotationPass(id='pass',invocation_id='synthetic-test-call',executor=C.Executor(id='test-labeler',kind='system'),status='success',input_hash=r.input_hash,prompt_revision='test-prompt',model_revision='scripted-contract-test',raw_output='synthetic output',decision=decision)
    return C.AnnotationV2(record_id=r.record_id,annotation_version='test',input_hash=r.input_hash,label_tier='G2',status='accepted',passes=(attempt,),final=decision)

@pytest.mark.parametrize('family',['relation','criterion','trajectory','acquisition'])
def test_fixture_bucket_and_metadata_never_enter_model_input(family):
    r=record(family);before=model_input(r);meta=metadata_projection(r)
    assert r.bucket=='fixture' and meta.bucket=='fixture' and meta.metadata_only
    assert meta.language==r.language and meta.lineage==r.lineage and meta.provenance==r.provenance
    assert meta.annotation_status=='unloaded' and meta.accepted_label_tier is None
    assert model_input(r)==before and C.digest(before)==r.input_hash
    assert not ({'bucket','language','lineage','provenance','label_tier','label_ref','source_snapshots'} & before.keys())

def test_fixture_marker_cannot_be_relabelled_env_run():
    r=record();raw=r.model_dump(mode='json');raw['provenance']['transformations'].append('fixture:not-business-run');raw['bucket']='env_run'
    with pytest.raises(ValidationError,match='fixture'):C.DatasetRecordV2.model_validate(raw)

def test_pending_tier_is_not_accepted_g1():
    r=record().model_copy(update={'label_tier':'G1'});pending=C.AnnotationV2(record_id=r.record_id,annotation_version='pending',input_hash=r.input_hash,label_tier='G1',status='pending',passes=())
    meta=metadata_projection(r,pending);assert meta.requested_label_tier=='G1' and meta.annotation_status=='pending' and meta.accepted_label_tier is None
    with pytest.raises(C.ProtocolError,match='annotation not accepted'):validate_record_annotation(r,pending,require_accepted=True)
    forged=pending.model_copy(update={'status':'accepted','final':accepted(record()).final})
    with pytest.raises(ValidationError):metadata_projection(r,forged)

def test_accepted_pair_requires_identity_tier_and_real_accepted_structure():
    r=record();annotation=accepted(r)
    assert validate_record_annotation(r,annotation,require_accepted=True)==annotation
    assert metadata_projection(r,annotation).accepted_label_tier=='G2'
    with pytest.raises(C.ProtocolError,match='annotation record mismatch'):metadata_projection(r,annotation.model_copy(update={'record_id':'different'}))
    with pytest.raises(C.ProtocolError,match='annotation record mismatch'):metadata_projection(r,annotation.model_copy(update={'input_hash':'f'*64,'passes':tuple(p.model_copy(update={'input_hash':'f'*64}) for p in annotation.passes)}))

def test_historical_reference_time_is_independent_of_capture_time():
    r=record(reference=5,until=10);annotation=accepted(r);capture=C.VersionPoint(business_seq=30,workspace_revision=30,storage_revision=40)
    snapshot=C.DatasetSnapshotMetadata(snapshot_digest='a'*64,source_digest=r.provenance.source.source_digest,session_id=r.lineage.session_id,capture_point=capture,origin='fixture')
    before=model_input(r);meta=metadata_projection(r,annotation,capture_point=capture,source_snapshots=(snapshot,))
    assert meta.capture_point.business_seq==30 and r.model_input.evidence.as_of.business_seq==5
    assert model_input(r)==before and meta.source_snapshots[0].snapshot_digest=='a'*64
    with pytest.raises(C.ProtocolError,match='capture precedes reference'):metadata_projection(r,annotation,capture_point=C.VersionPoint(business_seq=1,workspace_revision=1,storage_revision=1))

@pytest.mark.parametrize('until',[None,20])
def test_unknown_validity_does_not_become_accepted_or_open_ended(until):
    r=record(known=False,until=until);annotation=accepted(r)
    with pytest.raises(C.ProtocolError,match='temporal scope undetermined'):metadata_projection(r,annotation)
    pending=C.AnnotationV2(record_id=r.record_id,annotation_version='pending',input_hash=r.input_hash,label_tier='G2',status='pending',passes=())
    assert metadata_projection(r,pending).accepted_label_tier is None

def test_known_open_interval_is_explicit_and_expired_gold_is_rejected():
    open_record=record(known=True,until=None);assert metadata_projection(open_record,accepted(open_record)).accepted_label_tier=='G2'
    stale=record(known=True,until=3,reference=5)
    with pytest.raises(C.ProtocolError,match='annotation evidence not applicable'):validate_record_annotation(stale,accepted(stale),require_accepted=True)

def test_snapshot_metadata_cannot_change_origin_or_source_identity():
    r=record();point=C.VersionPoint(business_seq=9,workspace_revision=9,storage_revision=9)
    snapshot=C.DatasetSnapshotMetadata(snapshot_digest='b'*64,source_digest=r.provenance.source.source_digest,session_id=r.lineage.session_id,capture_point=point,origin='env_run')
    with pytest.raises(ValidationError,match='fixture'):metadata_projection(r,source_snapshots=(snapshot,))
    with pytest.raises(C.ProtocolError,match='snapshot source mismatch'):metadata_projection(r,source_snapshots=(snapshot.model_copy(update={'origin':'fixture','source_digest':'f'*64}),))


def test_fixture_snapshot_cannot_be_laundered_via_a_nonfixture_record():
    r=record().model_copy(update={'bucket':'env_run'});point=C.VersionPoint(business_seq=9,workspace_revision=9,storage_revision=9)
    snapshot=C.DatasetSnapshotMetadata(snapshot_digest='c'*64,source_digest=r.provenance.source.source_digest,session_id=r.lineage.session_id,capture_point=point,origin='fixture')
    with pytest.raises(ValidationError,match='fixture snapshot requires fixture'):metadata_projection(r,source_snapshots=(snapshot,))

def test_each_capture_snapshot_must_not_precede_the_historical_reference():
    r=record();point=C.VersionPoint(business_seq=1,workspace_revision=1,storage_revision=1)
    snapshot=C.DatasetSnapshotMetadata(snapshot_digest='d'*64,source_digest=r.provenance.source.source_digest,session_id=r.lineage.session_id,capture_point=point,origin='fixture')
    with pytest.raises(C.ProtocolError,match='capture precedes reference'):metadata_projection(r,source_snapshots=(snapshot,))


# The shared gate matches W08's legal joint-target rule. Empty alternatives are
# a legal target only for INSUFFICIENT/NOT_APPLICABLE, or when evidence is not
# being evaluated; one empty alternative must not bypass nonempty alternatives.
EVIDENCE_REQUIRED=[('relation','SUPPORTED'),('relation','CONTRADICTED'),('criterion','MET'),('criterion','PARTIAL'),('criterion','NOT_MET')]
EMPTY_TARGET_ALLOWED=[('relation','INSUFFICIENT'),('criterion','INSUFFICIENT'),('criterion','NOT_APPLICABLE')]

def with_decision(annotation,*,label,evaluable,ids=(),alternatives=()):
    decision=annotation.final.model_copy(update={'label':label,'evidence_evaluable':evaluable,'evidence_ids':ids,'acceptable_evidence_sets':alternatives,'applicability':'not_applicable' if label=='NOT_APPLICABLE' else 'applicable','missing_reason':None if evaluable else 'Synthetic non-evaluable boundary'})
    return annotation.model_copy(update={'final':decision,'passes':tuple(p.model_copy(update={'decision':decision}) for p in annotation.passes)})

@pytest.mark.parametrize('family,label',EVIDENCE_REQUIRED)
@pytest.mark.parametrize('mixed',[False,True])
def test_accepted_evaluable_conclusions_reject_any_empty_joint_target(family,label,mixed):
    r=record(family);candidate=r.model_input.evidence.candidate_evidence[0].id
    alternatives=((candidate,),()) if mixed else ((),)
    annotation=with_decision(accepted(r),label=label,evaluable=True,ids=(candidate,) if mixed else (),alternatives=alternatives)
    annotation=C.AnnotationV2.model_validate(annotation.model_dump(mode='json'))
    for check in (lambda:validate_record_annotation(r,annotation,require_accepted=True),lambda:metadata_projection(r,annotation)):
        with pytest.raises(C.ProtocolError,match='unsupported empty gold evidence'):check()

@pytest.mark.parametrize('family,label',EVIDENCE_REQUIRED)
def test_nonempty_legal_joint_target_still_accepts_supported_conclusions(family,label):
    r=record(family);candidate=r.model_input.evidence.candidate_evidence[0].id
    annotation=with_decision(accepted(r),label=label,evaluable=True,ids=(candidate,),alternatives=((candidate,),))
    assert validate_record_annotation(r,annotation,require_accepted=True)==annotation
    assert metadata_projection(r,annotation).accepted_label_tier=='G2'

@pytest.mark.parametrize('family,label',EMPTY_TARGET_ALLOWED)
def test_explicit_empty_target_remains_legal_for_insufficient_or_not_applicable(family,label):
    r=record(family);annotation=with_decision(accepted(r),label=label,evaluable=True,alternatives=((),))
    assert validate_record_annotation(r,annotation,require_accepted=True)==annotation

@pytest.mark.parametrize('family,label',EVIDENCE_REQUIRED+EMPTY_TARGET_ALLOWED)
def test_nonevaluable_annotations_do_not_require_fabricated_evidence(family,label):
    r=record(family);annotation=with_decision(accepted(r),label=label,evaluable=False)
    assert validate_record_annotation(r,annotation,require_accepted=True)==annotation
