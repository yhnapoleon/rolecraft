"""One disclosure boundary for prompt, material, history, attachment and export."""
from .world import SourceFragment, DisclosedFragment, DisclosureRecord, PublicDisclosureRecord, PublicDisclosureSource
from .core import ProtocolError

def project_fragments(fragments,actor_id,as_of_seq,*,include_expired=False):
    result=[]
    for raw in fragments:
        f=SourceFragment.model_validate(raw.model_dump(mode='json') if isinstance(raw,SourceFragment) else raw)
        ref=f.ref;policy=f.disclosure
        if ref.observed_at_seq>as_of_seq or ref.valid_from_seq>as_of_seq:continue
        if ref.valid_until_seq is not None and as_of_seq>ref.valid_until_seq and not include_expired:continue
        if policy.mode=='never':continue
        if policy.mode=='role_only' and actor_id not in policy.actors:continue
        if policy.mode=='paraphrase_only':
            if actor_id not in policy.actors:continue
            # The exact quote/span can contain a secret even when the visible text is safe.
            ref=ref.model_copy(update={'quote':None,'span_start':None,'span_end':None})
            text=policy.paraphrase
        else:text=f.text
        result.append(DisclosedFragment(ref=ref,text=text,channel=f.channel,fact_ids=f.fact_ids))
    return tuple(result)

def verify_disclosure_quotes(reply_text,records):
    records=tuple(DisclosureRecord.model_validate(x.model_dump(mode='json')) for x in records)
    if any(x.quote not in reply_text for x in records):raise ProtocolError('disclosure_quote_missing')
    return records


def project_disclosures(reply_text,records,*,session_id,as_of_seq):
    result=[]
    for record in verify_disclosure_quotes(reply_text,records):
        if record.source.session_id!=session_id or record.reply_ref.session_id!=session_id:raise ProtocolError('disclosure_session_mismatch')
        if record.displayed_at_seq is None or record.displayed_at_seq>as_of_seq or record.source.observed_at_seq>record.displayed_at_seq:raise ProtocolError('disclosure_time_mismatch')
        source=PublicDisclosureSource.model_validate(record.source.model_dump(mode='json')|{'quote':None,'span_start':None,'span_end':None})
        result.append(PublicDisclosureRecord.model_validate(record.model_dump(mode='json')|{'source':source.model_dump(mode='json')}))
    return tuple(result)

def project_feedback_content(content, source_readable, *, limited_scope=False):
    """Transient safe read of a saved report; never a replacement persisted result."""
    from copy import deepcopy
    from .core import canonical
    from .evaluation import FeedbackV2
    data=deepcopy(content)
    def refs(value):
        if isinstance(value,dict):
            if {'session_id','kind','object_id','version'}<=value.keys():yield value
            else:
                for part in value.values():yield from refs(part)
        elif isinstance(value,(list,tuple)):
            for part in value:yield from refs(part)
    hidden=any(not source_readable(ref) for ref in refs(data))
    counts_limited=limited_scope and (any(total.get('status')=='complete' for facts in data.get('verified_facts') or () for total in facts.get('activity_totals',{}).values()) or any(h.get('completeness')=='complete' for h in data.get('historical_responsibilities') or ()))
    if not hidden and not counts_limited and not limited_scope:return data,False
    unbound=hidden or limited_scope
    message='当前权限下部分支持依据不可核验，相关判断待核验。'
    for name in ('items','rule_items'):
        for item in data.get(name) or ():
            citations=item.get('citations',[]);available=[ref for ref in citations if source_readable(ref)]
            if len(available)!=len(citations) or (unbound and not citations):
                item.update(label='INSUFFICIENT',applicability='undetermined',source='pending',explanation=message,citations=available,rule_bound=None)
    for facts in data.get('verified_facts') or ():
        changed=False
        for check in facts.get('references',[]):
            ref=check.get('verified_ref')
            if ref is not None and not source_readable(ref):
                check.update(submitted_reference_hash=None,status='unavailable',verified_ref=None,valid_at_subject=None);changed=True
        kept=[]
        for row in facts.get('activity_records',[]):
            if source_readable(row['ref']) and (row.get('target') is None or source_readable(row['target'])):kept.append(row)
            else:changed=True
        facts['activity_records']=kept
        if changed or limited_scope:
            facts['status']='partial' if facts.get('as_of') is not None else 'unknown'
            facts['activity_window']=None
            for kind,total in facts.get('activity_totals',{}).items():total.update(status='unknown',count=None,verified_records=sum(row['kind']==kind for row in kept))
        if changed:
            facts.update(declared_source_count=None,declared_citation_count=None)
            available=[check['verified_ref'] for check in facts.get('references',[]) if check.get('verified_ref') is not None]
            facts['verified_source_count']=len({(r['session_id'],r['kind'],r['object_id'],r['version'],r.get('config_version')) for r in available})
        # Free summaries and the full snapshot digest have no per-fragment scope proof.
        if unbound:facts['summary']=[message]
        facts['source_snapshot_hash']=None
    for history in data.get('historical_responsibilities') or ():
        changed=False
        for row in history.get('entries',[]):
            sources=row.get('sources',[]);kept=[ref for ref in sources if source_readable(ref)]
            scope=[ref for ref in row.get('scope',[]) if source_readable(ref)]
            if len(kept)!=len(sources) or len(scope)!=len(row.get('scope',[])) or (unbound and not sources):
                row.update(kind='unknown',state='unknown',occurred_at=None,finding='unknown',explanation=message,sources=kept,scope=scope or [history['subject']],actor_id=None,executor=None);changed=True
        if changed or limited_scope:history.update(completeness='unknown',coverage=None)
        history['source_snapshot_hash']=None
    if unbound:
        data['business_response']=message;data['next_options']=['可补充当前可访问的依据，或由具备权限的人核对。']
        data['independent_understanding']='unobserved'
        applicable=[item for item in data['items'] if item['applicability']=='applicable']
        denominator=len(applicable)
        data['verified_coverage']=sum(item['source']=='verified_rule' and item['label']!='INSUFFICIENT' for item in applicable)/denominator if denominator else 0
        data['model_coverage']=sum(item['source']=='model_advice' and item['label']!='INSUFFICIENT' for item in applicable)/denominator if denominator else 0
    data['read_projection']='partial'
    FeedbackV2.model_validate(data)
    return data,True


def project_feedback_response_content(content, source_readable, *, parent_partial=False):
    from copy import deepcopy
    from .evaluation import FeedbackResponseRecord
    data=deepcopy(content);evidence=data.get('evidence',[]);available=[ref for ref in evidence if source_readable(ref)]
    if not parent_partial and len(available)==len(evidence):return data,False
    data.update(text='当前权限下回应内容或支持依据待核验。',evidence=available,read_projection='partial')
    FeedbackResponseRecord.model_validate(data)
    return data,True
