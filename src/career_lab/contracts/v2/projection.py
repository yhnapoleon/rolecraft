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

def feedback_segment(content,path):
    """Closed JSON-pointer subset for traced feedback text/derived sections."""
    import re
    allowed=(r'/(business_response|next_options|independent_understanding|text)',r'/(items|rule_items)/[0-9]+(?:/explanation)?',r'/verified_facts/[0-9]+(?:/(summary|activity_totals|activity_window|source_snapshot_hash))?',r'/historical_responsibilities/[0-9]+(?:/(coverage|source_snapshot_hash)|/entries/[0-9]+(?:/explanation)?)?')
    if not any(re.fullmatch(pattern,path) for pattern in allowed):raise ProtocolError('feedback_trace_path_invalid',status=403)
    value=content
    try:
        for part in path[1:].split('/'):value=value[int(part)] if isinstance(value,(list,tuple)) else value[part]
    except (KeyError,IndexError,TypeError,ValueError):raise ProtocolError('feedback_trace_path_invalid',status=403) from None
    return value


def _feedback_boundary_reader(content,source_readable):
    from .core import digest
    def allowed(path):
        covered=[proof for proof in content.get('read_boundaries') or () if path==proof['path'] or path.startswith(proof['path']+'/')]
        if not covered:return False
        specificity=max(len(proof['path'].split('/')) for proof in covered)
        selected=[proof for proof in covered if len(proof['path'].split('/'))==specificity]
        for proof in selected:
            try:value=feedback_segment(content,proof['path'])
            except ProtocolError:return False
            if proof.get('attestation')!='common_store_trace_v1' or proof['content_hash']!=digest(value) or not proof['dependencies'] or not all(source_readable(ref) for ref in proof['dependencies']):return False
        return True
    return allowed


def project_feedback_content(content, source_readable, *, limited_scope=False):
    """Per-segment authorization; a finite object grant alone is not redaction."""
    from copy import deepcopy
    from .core import canonical
    from .evaluation import FeedbackV2
    original=content;data=deepcopy(content)
    def refs(value):
        if isinstance(value,dict):
            if {'session_id','kind','object_id','version'}<=value.keys():yield value
            else:
                for part in value.values():yield from refs(part)
        elif isinstance(value,(list,tuple)):
            for part in value:yield from refs(part)
    hidden=any(not source_readable(ref) for ref in refs(original))
    proof=_feedback_boundary_reader(original,source_readable)
    def declared(path):return any(path==boundary['path'] or path.startswith(boundary['path']+'/') for boundary in original.get('read_boundaries') or ())
    def text_allowed(path):return proof(path) or (not limited_scope and not hidden and not declared(path))
    message='当前权限下部分支持依据不可核验，相关判断待核验。'
    for name in ('items','rule_items'):
        for index,item in enumerate(data.get(name) or ()):
            citations=item.get('citations',[]);available=[ref for ref in citations if source_readable(ref)]
            path=f'/{name}/{index}/explanation'
            if len(available)!=len(citations) or (declared(path) and not proof(path)) or (not citations and not text_allowed(path)):
                item.update(label='INSUFFICIENT',applicability='undetermined',source='pending',explanation=message,citations=available,rule_bound=None)
    for index,facts in enumerate(data.get('verified_facts') or ()):
        base=f'/verified_facts/{index}';changed=False
        for check in facts.get('references',[]):
            ref=check.get('verified_ref')
            if ref is not None and not source_readable(ref):check.update(submitted_reference_hash=None,status='unavailable',verified_ref=None,valid_at_subject=None);changed=True
        kept=[]
        for row in facts.get('activity_records',[]):
            if source_readable(row['ref']) and (row.get('target') is None or source_readable(row['target'])):kept.append(row)
            else:changed=True
        facts['activity_records']=kept
        if changed or not text_allowed(base+'/activity_totals'):
            facts['status']='partial' if facts.get('as_of') is not None else 'unknown';facts['activity_window']=None
            for kind,total in facts.get('activity_totals',{}).items():total.update(status='unknown',count=None,verified_records=sum(row['kind']==kind for row in kept))
        if changed:
            facts.update(declared_source_count=None,declared_citation_count=None)
            available=[check['verified_ref'] for check in facts.get('references',[]) if check.get('verified_ref') is not None]
            facts['verified_source_count']=len({(r['session_id'],r['kind'],r['object_id'],r['version'],r.get('config_version')) for r in available})
        if not text_allowed(base+'/summary'):facts['summary']=[message]
        if not text_allowed(base+'/source_snapshot_hash'):facts['source_snapshot_hash']=None
    for index,history in enumerate(data.get('historical_responsibilities') or ()):
        base=f'/historical_responsibilities/{index}';changed=False
        for number,row in enumerate(history.get('entries',[])):
            sources=row.get('sources',[]);kept=[ref for ref in sources if source_readable(ref)];scope=[ref for ref in row.get('scope',[]) if source_readable(ref)]
            path=base+f'/entries/{number}/explanation'
            if len(kept)!=len(sources) or len(scope)!=len(row.get('scope',[])) or (declared(path) and not proof(path)) or (not sources and not text_allowed(path)):
                row.update(kind='unknown',state='unknown',occurred_at=None,finding='unknown',explanation=message,sources=kept,scope=scope or [history['subject']],actor_id=None,executor=None);changed=True
        if changed or not text_allowed(base+'/coverage'):history.update(completeness='unknown',coverage=None)
        if not text_allowed(base+'/source_snapshot_hash'):history['source_snapshot_hash']=None
    if not text_allowed('/business_response'):data['business_response']=message
    if not text_allowed('/next_options'):data['next_options']=['可补充当前可访问的依据，或由具备权限的人核对。']
    if not text_allowed('/independent_understanding'):data['independent_understanding']='unobserved'
    if any(data.get(name)!=original.get(name) for name in ('items','rule_items')):
        applicable=[item for item in data['items'] if item['applicability']=='applicable'];denominator=len(applicable)
        data['verified_coverage']=sum(item['source']=='verified_rule' and item['label']!='INSUFFICIENT' for item in applicable)/denominator if denominator else 0
        data['model_coverage']=sum(item['source']=='model_advice' and item['label']!='INSUFFICIENT' for item in applicable)/denominator if denominator else 0
    if data.get('read_boundaries') is not None:
        data['read_boundaries']=[boundary for boundary in data['read_boundaries'] if proof(boundary['path']) and feedback_segment(data,boundary['path'])==feedback_segment(original,boundary['path'])]
    if canonical(data)==canonical(original):return data,False
    data['read_projection']='partial';FeedbackV2.model_validate(data);return data,True


def project_feedback_response_content(content, source_readable, *, parent_partial=False):
    from copy import deepcopy
    from .evaluation import FeedbackResponseRecord
    data=deepcopy(content);evidence=data.get('evidence',[]);available=[ref for ref in evidence if source_readable(ref)]
    proof=_feedback_boundary_reader(content,source_readable)
    text_allowed=proof('/text') or (content.get('read_boundaries') is None and not parent_partial)
    if text_allowed and len(available)==len(evidence):return data,False
    data.update(text='当前权限下回应内容或支持依据待核验。',evidence=available,read_projection='partial')
    if data.get('read_boundaries') is not None:data['read_boundaries']=[]
    FeedbackResponseRecord.model_validate(data);return data,True
