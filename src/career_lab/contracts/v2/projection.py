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
