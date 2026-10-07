"""Convert owned factual output to the fixed c9 public feedback sections.

No guessed source identity, occurrence time, actor or log completeness. Unknown historical occurrence times remain None in the official c9 finding;
no timestamp or source metadata is fabricated.
"""
from career_lab.contracts import v2 as C
from .localization import message,validate_language
from .availability import SAFE_REASON


def sections(reader,auth,subject,requested_at,facts,history,*,work_language='zh'):
    captured=getattr(reader,'captured_at',None);snapshot_hash=getattr(reader,'snapshot_sha256',None)
    if captured is None or snapshot_hash is None:raise C.ProtocolError('source_capture_required',status=503)
    # The input file hash is an internal integrity check. Public provenance binds
    # the authorized projection actually used, so hidden-vs-missing source bytes
    # cannot be distinguished through a published whole-private-file hash.
    projected_refs=[]
    for row in facts.get('references',()):
        exact=row['status']=='exact_reference_verified'
        projected_refs.append({'submitted_reference_hash':C.digest(row['ref']),'status':row['status'],
            'verified_ref':row['ref'] if exact else None,'valid_at_subject':row['valid_at_subject'] if exact else None})
    source_projection={'subject':subject.model_dump(mode='json'),'as_of':facts.get('as_of'),
        'requested_at':requested_at.model_dump(mode='json'),'captured_at':captured.model_dump(mode='json'),
        'references':projected_refs,'activities':facts.get('activity_records',[]),'activity_totals':facts.get('activity_totals',{}),
        'authorship':facts.get('authorship',{}),'actor_id':auth.actor_id,
        'historical_sources':[{k:r.get(k) for k in ('criterion','kind','state','occurred_at','scope','sources','actor_id','executor')} for r in history if r['sources']]}
    public_hash=C.digest(['authorized-source-projection-v1',source_projection])
    base={'subject':subject,'as_of':facts.get('as_of'),'requested_at':requested_at,
          'captured_at':captured,'source_snapshot_hash':public_hash}
    if base['as_of'] is None:
        factual=C.VerifiedFactsSnapshot(**base,status='unknown',summary=tuple(facts.get('summary',())),actor_id=auth.actor_id)
    else:
        checks=[]
        for row in facts['references']:
            exact=row['status']=='exact_reference_verified'
            checks.append(C.FeedbackReferenceCheck(submitted_reference_hash=C.digest(row['ref']),status=row['status'],
                verified_ref=C.EvidenceRefV2.model_validate(row['ref']) if exact else None,
                valid_at_subject=row['valid_at_subject'] if exact else None))
        partial=any(r.status!='exact_reference_verified' or r.valid_at_subject is not True for r in checks) or any(v['status']=='unknown' for v in facts['activity_totals'].values())
        authors=facts['authorship']
        factual=C.VerifiedFactsSnapshot(**base,status='partial' if partial else 'verified',references=tuple(checks),
            activity_records=tuple(C.FeedbackActivity.model_validate(r) for r in facts['activity_records']),
            activity_totals={k:C.FeedbackActivityCount.model_validate(v) for k,v in facts['activity_totals'].items()},
            activity_window=C.FeedbackActivityWindow.model_validate(facts['activity_window']) if facts.get('activity_window') else None,
            declared_source_count=facts['declared_source_count'],declared_citation_count=facts['declared_citation_count'],
            verified_source_count=facts['exact_source_count'],author=authors['author'],executor=authors['executor'],adopter=authors['adopter'],
            actor_id=auth.actor_id,summary=tuple(facts['summary']))
    entries=[];pending=[]
    for raw in history:
        if raw['occurred_at'] is None:
            pending_message=raw['criterion']+': '+message(work_language,SAFE_REASON)
            if pending_message not in pending:pending.append(pending_message)
        data={k:v for k,v in raw.items() if k in C.HistoricalResponsibilityFinding.model_fields}
        entries.append(C.HistoricalResponsibilityFinding.model_validate(data))
    historical=C.HistoricalResponsibilitiesSnapshot(**base,completeness='partial' if entries or pending else 'unknown',entries=tuple(entries))
    return factual,historical,pending


def attach_sections(report,reader,auth,subject,requested_at,facts,history,rule_items,extra_notes=(),*,work_language='zh'):
    factual,historical,pending=sections(reader,auth,subject,requested_at,facts,history,work_language=work_language)
    raw=report.model_dump(mode='json')
    raw.update(as_of=requested_at.model_dump(mode='json'),verified_facts=[factual.model_dump(mode='json')],
        historical_responsibilities=[historical.model_dump(mode='json')],rule_items=rule_items,
        next_options=list(dict.fromkeys([*raw['next_options'],*pending,*extra_notes])))
    return C.FeedbackV2.model_validate(raw)
