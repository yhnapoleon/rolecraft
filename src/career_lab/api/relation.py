"""Experimental relation checks are saved separately and never alter rubric scores."""
import json
from pathlib import Path
from career_lab.contracts.evaluation import CandidateEvidence, EvidencePackage
from career_lab.evidence.serializer import seal_input
from career_lab.experiments.protocol import verify_freeze
from career_lab.experiments.study import candidates
from career_lab.storage.sessions import IdempotencyConflict, digest


def shadow_check(store,study,session_id,claim,request_id,as_of_seq=None):
    request_hash=digest(dict(claim=claim,request_id=request_id,as_of_seq=as_of_seq))
    oid=digest([session_id,'shadow-relation',request_id])
    try:
        previous=store.get_object(session_id,oid,'shadow_relation')
    except KeyError:previous=None
    if previous:
        if previous['request_hash']!=request_hash:raise IdempotencyConflict('relation request reused with different content')
        return previous
    study=Path(study)
    frozen=verify_freeze(study/'freeze.json')
    report=json.loads((study/'confirmatory.json').read_text(encoding='utf-8'))
    if report['freeze_id']!=frozen['id'] or report['report_hash']!=digest({k:v for k,v in report.items() if k!='report_hash'}):
        raise ValueError('shadow evaluation report mismatch')
    state=store.get_state(session_id,as_of_seq)
    view=store.project_view(session_id,'learner',state.version)
    evidence=[];sources={}
    for material in view.permitted_materials:
        eid=f'e{len(evidence)+1}'
        evidence.append(CandidateEvidence(id=eid,version=material.version,text=material.content))
        sources[eid]=dict(kind='document',object_id=material.id,version=material.version,as_of_seq=state.version)
    eid=f'e{len(evidence)+1}'
    evidence.append(CandidateEvidence(id=eid,version=max(1,state.config_version),text=json.dumps({'resources':state.resources,'pilot':state.configs.get('pilot')},ensure_ascii=False)))
    sources[eid]=dict(kind='config',object_id='pilot',version=max(1,state.config_version),as_of_seq=state.version)
    item=seal_input(EvidencePackage(item_id=oid,task_type='relation',criterion='user_claim',claim=claim,as_of_seq=state.version,
        candidate_evidence=tuple(evidence),completeness='complete'))
    selected=frozen['decision']['selected'];model=candidates(frozen['decision']['models'])[selected]
    prediction=model.judge(item)
    if not set(prediction.evidence_ids)<=sources.keys():raise ValueError('invalid model citation')
    result=dict(id=oid,mode='shadow',review_required=True,affects_score=False,request_hash=request_hash,
        input_hash=item.input_hash,as_of_seq=state.version,freeze_id=frozen['id'],model_revision=model.revision,
        decision=prediction.model_dump(mode='json'),sources=sources,
        limitation='仅在受控合成语法上验证，当前自由文本输入可能分布不同；需要人工复核，不用于正式评分。')
    return store.save_derived(session_id,oid,'shadow_relation',result)
