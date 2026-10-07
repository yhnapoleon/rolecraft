"""Verified reference and activity facts. No conclusion-quality or ability score."""
from career_lab.contracts.v2.core import ProtocolError,VersionPoint,canonical
from .ports import ActivityLedger
from .history import before

KINDS=('material_read','test_run','question_sent','reply_received','learner_displayed')
NAMES={'material_read':'材料读取','test_run':'测试运行','question_sent':'向同事提问','reply_received':'实际收到回复','learner_displayed':'向学员展示'}


def reference_key(ref):
    return (ref.session_id,ref.kind,ref.object_id,ref.version,ref.config_version)


def factual_feedback(reader,auth,subject,at,requested_at):
    from .assembler import EvidenceAssemblerV2
    record=reader.read(auth,subject,at);resolver=EvidenceAssemblerV2(reader)
    if record.created_at!=at:raise ProtocolError('subject_point_mismatch',status=409)
    refs=[];seen=set();source_keys=set();valid_sources=set()
    for ref in record.declared_refs:
        key=canonical(ref)
        if key in seen:continue
        seen.add(key);source_keys.add(reference_key(ref))
        row={'ref':ref.model_dump(mode='json'),'status':'unavailable','valid_at_subject':None,'semantic_support':'not_established'}
        try:
            resolved=resolver.resolve(auth,ref,at)
            row.update(status='exact_reference_verified',valid_at_subject=resolved.ref.valid_until_seq is None or at.business_seq<resolved.ref.valid_until_seq)
            valid_sources.add(reference_key(ref))
        except KeyError:pass
        except ProtocolError as error:
            if error.code in {'future_evidence','evidence_version_mismatch','evidence_quote_mismatch','evidence_time_mismatch','source_time_unknown'}:row['status']=error.code
            elif error.status in {403,404}:row['status']='unavailable'
            else:raise
        refs.append(row)
    ledger=reader.activity_log(auth,at) if hasattr(reader,'activity_log') else ActivityLedger()
    zero=VersionPoint(business_seq=0,workspace_revision=0,storage_revision=0)
    complete=dict(ledger.completeness)
    full_window=(ledger.covered_from is not None and before(ledger.covered_from,zero)
                 and ledger.covered_through is not None and before(at,ledger.covered_through)
                 and ledger.captured_at is not None and before(at,ledger.captured_at)
                 and auth.allowed_objects is None)
    rows=[];broken=set();seen_events=set()
    for event in ledger.records:
        if event.kind not in KINDS:raise ProtocolError('invalid_activity_kind')
        if not before(event.occurred_at,at):continue
        key=reference_key(event.ref)
        if key in seen_events:continue
        seen_events.add(key)
        try:
            checked=resolver.resolve(auth,event.ref,at)
            source=reader.read(auth,event.ref,at)
            if source.created_at!=event.occurred_at or source.executor is None or source.executor!=event.executor or source.activity_kind!=event.kind or source.activity_target!=event.target or source.actor_id!=event.actor_id:
                raise ProtocolError('activity_provenance_mismatch')
            if event.ref.session_id!=auth.session_id:raise ProtocolError('activity_provenance_mismatch')
            if event.kind in {'reply_received','learner_displayed'}:
                if event.target is None:raise ProtocolError('activity_target_missing')
                resolver.resolve(auth,event.target,event.occurred_at)
                target=reader.read(auth,event.target,event.occurred_at)
                expected='question_sent' if event.kind=='reply_received' else 'reply_received'
                if target.activity_kind!=expected:raise ProtocolError('activity_target_mismatch')
            rows.append({'kind':event.kind,'ref':checked.ref.model_dump(mode='json'),'occurred_at':event.occurred_at.model_dump(mode='json'),
                         'executor':event.executor.model_dump(mode='json'),'actor_id':event.actor_id,
                         'target':event.target.model_dump(mode='json') if event.target else None,'counterparty':event.counterparty})
        except (KeyError,ProtocolError):broken.add(event.kind)
    from career_lab.contracts.v2.core import EvidenceRefV2,ObjectRef
    present={(r['kind'],reference_key(EvidenceRefV2.model_validate(r['ref']))) for r in rows}
    for row in rows:
        if row['kind'] in {'reply_received','learner_displayed'} and row['target']:
            expected='question_sent' if row['kind']=='reply_received' else 'reply_received'
            if (expected,reference_key(ObjectRef.model_validate(row['target']))) not in present:broken.add(expected)
    totals={}
    for kind in KINDS:
        actual=[r for r in rows if r['kind']==kind]
        known=full_window and complete.get(kind) is True and kind not in broken
        totals[kind]={'status':'complete' if known else 'unknown','count':len(actual) if known else None,
                      'verified_records':len(actual)}
    summary=[f'作品明确关联{len(source_keys)}个来源、{len(refs)}处去重引用；已核对{len(valid_sources)}个来源的确切版本与原文。引用真实不等于支持结论。']
    for kind in KINDS:
        value=totals[kind]
        if value['status']=='complete':summary.append(f'作品形成前完整授权日志中的{NAMES[kind]}记录：{value["count"]}条。')
        else:summary.append(f'{NAMES[kind]}日志完整性未知；已核实{value["verified_records"]}条，不能据此断言没有发生。')
    if any(r['executor']['kind']=='external_agent' for r in rows):summary.append('含外部Agent执行记录；不视为学员独立调查或理解。')
    summary.append('提问、收到回复、向学员展示和理解分别记录；当前无法判断独立理解。')
    return {'section':'verified_facts','subject':subject.model_dump(mode='json'),'as_of':at.model_dump(mode='json'),
            'requested_at':requested_at.model_dump(mode='json'),'reference_grain':'exact_ref_and_quote; source_count_by_object_version_config',
            'declared_source_count':len(source_keys),'declared_citation_count':len(refs),'verified_source_count':len(valid_sources),
            'references':refs,'activity_records':rows,'activity_totals':totals,'summary':summary,
            'authorship':{k:getattr(record,k).model_dump(mode='json') if getattr(record,k) else None for k in ['author','executor','adopter']},
            'independent_understanding':'unobserved','conclusion_quality':'not_scored'}
