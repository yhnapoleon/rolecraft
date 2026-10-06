"""One disclosure boundary for prompt, material, history, attachment and export."""
from .world import SourceFragment, DisclosedFragment, DisclosureRecord
from .core import ProtocolError

def project_fragments(fragments,actor_id,as_of_seq):
    result=[]
    for raw in fragments:
        f=SourceFragment.model_validate(raw.model_dump(mode='json') if isinstance(raw,SourceFragment) else raw)
        ref=f.ref;policy=f.disclosure
        if ref.observed_at_seq>as_of_seq or ref.valid_from_seq>as_of_seq:continue
        if policy.mode=='never':continue
        if policy.mode=='role_only' and actor_id not in policy.actors:continue
        if policy.mode=='paraphrase_only':
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
