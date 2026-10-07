"""N-W07-01: independently valid passes may use different explanatory wording.

The positive accepted-consensus checks intentionally expose an incompatible
frozen public contract. They must pass on an authorized compatible candidate.
"""
import json
from copy import deepcopy
import pytest
from test_w07_pipeline import batch_for,signed,label_result,decision,FakeModel
from career_lab.contracts.v2.core import ProtocolError,digest,FileRef
from career_lab.contracts.v2.data import AnnotationV2
from career_lab.datasets.v3.attestation import same_semantics,verify_attempt,rebuild_annotation,parse_receipt,make_request
from career_lab.datasets.v3.labeling import AnnotationBatch
from career_lab.datasets.v3.release import publish_release,audit_release
from career_lab.datasets.v3.common import json_bytes,sha


def equivalent(request,kind):
    raw=decision(request).model_dump(mode='json')
    if kind=='wording':raw.update(label='INSUFFICIENT',evidence_ids=[],acceptable_evidence_sets=[[]],missing_reason='need source confirmation' if request['phase']==1 else 'support is still unverified')
    else:raw.update(evidence_ids=['e1'] if request['phase']==1 else ['e2'],acceptable_evidence_sets=[['e1'],['e2']])
    return raw


@pytest.mark.parametrize('kind',['wording','representative'])
@pytest.mark.parametrize('mode',['online','resume','offline'])
def test_equivalent_semantics_use_two_calls_keep_first_and_publish(tmp_path,kind,mode):
    batch,result,policies=batch_for(tmp_path);rid=result.records[0].record_id;calls=[]
    def executor(request):
        calls.append(request['phase']);assert request['phase'] in [1,2]
        return label_result(request,json.dumps(equivalent(request,kind)),usage={'cost':1.})
    if mode in ['offline','resume']:
        request=batch.claim(rid,1);calls.append(1);batch.receive(signed(request,json.dumps(equivalent(request,kind))) | {'usage':{'cost':1.}})
        batch=AnnotationBatch(batch.path)
    if mode=='offline':
        request=batch.claim(rid,2);calls.append(2);batch.receive(signed(request,json.dumps(equivalent(request,kind))) | {'usage':{'cost':1.}})
    else:batch.run(executor)
    annotation=batch.annotation(rid)
    assert calls==[1,2] and batch.usage()['known_cost']==2.
    assert same_semantics(annotation.passes[0].decision,annotation.passes[1].decision)
    assert annotation.passes[0].raw_output!=annotation.passes[1].raw_output
    assert not batch.run(executor)['usage']['uncertain'] and calls==[1,2]
    with pytest.raises(ProtocolError,match='not required'):batch.claim(rid,3)
    assert annotation.status=='accepted','public AnnotationV2 must permit the authorized semantic consensus'
    assert annotation.final==annotation.passes[0].decision and annotation.adjudication_ref is None
    publish_release(tmp_path/'release',result,source_root=tmp_path,policies=policies,annotations=[annotation],annotation_artifacts=batch.artifacts(),fixture=True)
    assert audit_release(tmp_path/'release')['annotation_status']=={'accepted':1}
    # Even a semantically equivalent final cannot be switched from the first pass.
    swapped=annotation.model_copy(update={'final':annotation.passes[1].decision})
    with pytest.raises((ProtocolError,ValueError)):
        publish_release(tmp_path/'swapped',result,source_root=tmp_path,policies=policies,annotations=[swapped],annotation_artifacts=batch.artifacts(),fixture=True)


def test_true_disagreement_still_uses_actual_third_pass(tmp_path):
    batch,result,_=batch_for(tmp_path);model=FakeModel({1:'SUPPORTED',2:'CONTRADICTED',3:'SUPPORTED'})
    out=batch.run(model);assert [r['phase'] for r in model.calls]==[1,2,3]
    a=out['annotations'][0];assert a.status=='accepted' and a.adjudication_ref and a.final==a.passes[2].decision


def test_invalid_representative_is_failed_before_semantic_comparison(tmp_path):
    batch,result,_=batch_for(tmp_path);calls=[]
    def executor(request):
        calls.append(request['phase']);raw=equivalent(request,'representative')
        if request['phase']==2:raw['evidence_ids']=['missing']
        return label_result(request,json.dumps(raw))
    out=batch.run(executor);assert calls==[1,2] and out['annotations'][0].status=='pending'
    assert out['annotations'][0].passes[1].status=='failed'


def test_forced_third_phase_and_raw_parsed_drift_are_rejected(tmp_path):
    batch,result,_=batch_for(tmp_path);record=result.records[0]
    for phase in [1,2]:
        request=batch.claim(record.record_id,phase);batch.receive(signed(request,json.dumps(equivalent(request,'wording'))))
    verified=[]
    for raw in batch.artifacts().values():
        stored,parsed=verify_attempt(record,batch.manifest['annotation_version'],raw);verified.append((stored,parsed,raw))
    first=deepcopy(verified[0][0]);changed=json.loads(first['receipt']['raw_output']);changed['missing_reason']='changed words, same semantics'
    first['receipt']['raw_output']=json.dumps(changed);first['receipt_hash']=digest(first['receipt'])
    with pytest.raises(ProtocolError,match='raw decision mismatch'):verify_attempt(record,batch.manifest['annotation_version'],json_bytes(first))
    request=make_request(record,batch.manifest['annotation_version'],3,1,batch.manifest['prompts'][2],batch.manifest['executor'],batch.approvals[record.record_id],batch.manifest['id'],batch.manifest['output_schema'])
    request['request_hash']=digest(request)
    receipt=signed(request);request.pop('request_hash');parsed,error,raw_type=parse_receipt(request,receipt)
    forced=deepcopy(verified[0][0]);forced.update(request=request,request_hash=digest(request),receipt=receipt,receipt_hash=digest(receipt),**{'pass':parsed.model_dump(mode='json')},provider=receipt['provider'],usage={},elapsed_seconds=None,error_code=error,raw_return_type=raw_type)
    raw=json_bytes(forced);stored,parsed=verify_attempt(record,batch.manifest['annotation_version'],raw)
    with pytest.raises(ProtocolError,match='unneeded adjudication'):rebuild_annotation(record,batch.manifest['annotation_version'],[*verified,(stored,parsed,raw)])
    with pytest.raises(ProtocolError):batch.receive(receipt)


def test_old_batch_protocol_is_not_silently_reinterpreted(tmp_path):
    batch,_,_=batch_for(tmp_path);path=batch.path/'batch.json';raw=json.loads(path.read_text());raw['protocol']='w07-label-outbox-v3';raw['id']=digest({k:v for k,v in raw.items() if k!='id'});path.write_bytes(json_bytes(raw))
    with pytest.raises(ProtocolError,match='revalidation'):AnnotationBatch(batch.path)


def test_forced_phase_three_cannot_enter_publication_or_rehashed_audit(tmp_path):
    batch,result,policies=batch_for(tmp_path);record=result.records[0];a=batch.run(FakeModel())["annotations"][0]
    root=tmp_path/'release';publish_release(root,result,source_root=tmp_path,policies=policies,annotations=[a],annotation_artifacts=batch.artifacts(),fixture=True)
    first=json.loads(next(iter(batch.artifacts().values())))
    request=make_request(record,batch.manifest['annotation_version'],3,1,batch.manifest['prompts'][2],batch.manifest['executor'],batch.approvals[record.record_id],batch.manifest['id'],batch.manifest['output_schema'])
    receipt=signed(request | {'request_hash':digest(request)});parsed,error,raw_type=parse_receipt(request,receipt)
    forced=deepcopy(first);forced.update(request=request,request_hash=digest(request),receipt=receipt,receipt_hash=digest(receipt),**{'pass':parsed.model_dump(mode='json')},provider=receipt['provider'],usage={},elapsed_seconds=None,error_code=error,raw_return_type=raw_type)
    raw=json_bytes(forced);verify_attempt(record,batch.manifest['annotation_version'],raw)
    path='labels/passes/'+parsed.id+'.json';artifacts=batch.artifacts() | {path:raw}
    forged=AnnotationV2.model_validate(a.model_dump(mode='json') | {'passes':[p.model_dump(mode='json') for p in (*a.passes,parsed)],'adjudication_ref':FileRef(path=path,sha256=sha(raw)).model_dump(mode='json')})
    with pytest.raises(ProtocolError,match='unneeded adjudication'):
        publish_release(tmp_path/'forced',result,source_root=tmp_path,policies=policies,annotations=[forged],annotation_artifacts=artifacts,fixture=True)
    # Replay attack recalculates all outer checksums of an already published release.
    (root/path).write_bytes(raw);label_path='labels/'+record.record_id+'.json';(root/label_path).write_bytes(json_bytes(forged))
    records=json.loads((root/'records.json').read_text());records[0]['label_ref']['sha256']=sha((root/label_path).read_bytes());(root/'records.json').write_bytes(json_bytes(records))
    manifest=json.loads((root/'manifest.json').read_text());manifest['files'][path]=sha(raw)
    manifest['files']={name:sha((root/name).read_bytes()) for name in manifest['files']};manifest['id']=digest({k:v for k,v in manifest.items() if k!='id'});(root/'manifest.json').write_bytes(json_bytes(manifest))
    with pytest.raises(ProtocolError,match='unneeded adjudication'):audit_release(root)
