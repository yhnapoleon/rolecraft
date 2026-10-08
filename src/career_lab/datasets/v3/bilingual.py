"""Internal translation evidence checks, consuming c5 records without new schema.

This is a publisher/auditor input, not a work_language/session contract. Original
UTF-8 source bytes and model-visible text anchors must be available to audit it.
Translation meaning/label quality remain a separate review requirement.
"""
from dataclasses import dataclass
from collections import Counter
from pathlib import Path
import hashlib

from career_lab.contracts.v2.core import FileRef,Executor,ProtocolError,digest,read_file

LANGUAGES=('zh','en')
PROTOCOL='w07-translation-evidence-v1'


@dataclass(frozen=True)
class TextAnchor:
    file: FileRef
    text_path: tuple
    span_start: int
    span_end: int
    quote: str


@dataclass(frozen=True)
class TranslationPair:
    id: str
    original_record_id: str
    translated_record_id: str
    original: TextAnchor
    translated: TextAnchor
    executor: Executor
    revision: str


def visible_text(item,path):
    allowed=(len(path)==4 and path[:2]==('evidence','candidate_evidence') and type(path[2]) is int and path[3]=='text') or path==('evidence','claim')
    allowed=allowed or (len(path)==4 and path[0] in {'steps','observed_steps'} and type(path[1]) is int and path[2]=='observations' and type(path[3]) is int)
    if not allowed:raise ProtocolError('translation_anchor_path_not_allowed')
    value=item.model_dump(mode='json')
    try:
        for key in path:
            if isinstance(key,int) and key<0:raise ValueError('negative index')
            value=value[key]
    except (KeyError,IndexError,TypeError,ValueError) as exc:raise ProtocolError('translation_anchor_path_invalid') from exc
    if not isinstance(value,str) or not value:raise ProtocolError('translation_anchor_text_required')
    return value


def anchor_dict(anchor):
    return {'file':anchor.file.model_dump(mode='json'),'text_path':list(anchor.text_path),
            'span_start':anchor.span_start,'span_end':anchor.span_end,'quote':anchor.quote}


def pair_dict(pair):
    return {'id':pair.id,'original_record_id':pair.original_record_id,'translated_record_id':pair.translated_record_id,
            'original':anchor_dict(pair.original),'translated':anchor_dict(pair.translated),
            'executor':pair.executor.model_dump(mode='json'),'revision':pair.revision}


def read_pairs(raw):
    if raw.get('protocol')!=PROTOCOL:raise ProtocolError('translation_evidence_protocol_invalid')
    try:
        def anchor(value):return TextAnchor(FileRef.model_validate(value['file']),tuple(value['text_path']),value['span_start'],value['span_end'],value['quote'])
        return [TranslationPair(v['id'],v['original_record_id'],v['translated_record_id'],anchor(v['original']),anchor(v['translated']),Executor.model_validate(v['executor']),v['revision']) for v in raw['pairs']]
    except (KeyError,TypeError,ValueError) as exc:raise ProtocolError('translation_evidence_invalid') from exc


def verify_anchor(record,anchor,source_root):
    if anchor.file not in record.provenance.actual_sources:raise ProtocolError('translation_source_not_in_provenance')
    if anchor.file.media_type!='text/plain':raise ProtocolError('translation_source_requires_utf8_text_artifact')
    raw=read_file(Path(source_root),anchor.file)
    try:text=raw.decode('utf-8')
    except UnicodeDecodeError as exc:raise ProtocolError('translation_source_not_utf8') from exc
    start,end=anchor.span_start,anchor.span_end
    if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text):raise ProtocolError('translation_span_invalid')
    if not isinstance(anchor.quote,str) or text[start:end]!=anchor.quote:raise ProtocolError('translation_span_quote_mismatch')
    if visible_text(record.model_input,anchor.text_path)!=anchor.quote:raise ProtocolError('translation_quote_not_model_visible')
    return {'file':anchor.file.model_dump(mode='json'),'text_path':list(anchor.text_path),
            'span_start':start,'span_end':end,'quote_sha256':hashlib.sha256(anchor.quote.encode()).hexdigest()}


def verify_pairs(records,pairs,contexts):
    rows={r.record_id:r for r in records};seen=set();edges=set();out=[]
    for pair in pairs:
        if not pair.id or pair.id in seen:raise ProtocolError('translation_pair_identity_invalid')
        seen.add(pair.id)
        if not pair.revision.strip():raise ProtocolError('translation_revision_required')
        Executor.model_validate(pair.executor.model_dump(mode='json'))
        a=rows.get(pair.original_record_id);b=rows.get(pair.translated_record_id)
        if a is None or b is None or a.record_id==b.record_id:raise ProtocolError('translation_pair_member_missing')
        edge=(a.record_id,b.record_id)
        if edge in edges:raise ProtocolError('duplicate_translation_pair')
        edges.add(edge)
        if {a.language,b.language}!=set(LANGUAGES):raise ProtocolError('translation_requires_zh_en_pair')
        if a.family!=b.family:raise ProtocolError('translation_family_mismatch')
        if a.split!=b.split:raise ProtocolError('translation_cross_split')
        x,y=a.lineage,b.lineage
        if x.structure_id!=y.structure_id or x.component_id!=y.component_id or not x.fact_root_ids or set(x.fact_root_ids)!=set(y.fact_root_ids):
            raise ProtocolError('translation_causal_group_mismatch')
        if a.record_id not in y.source_record_ids or pair.id not in set(x.derivation_ids)&set(y.derivation_ids):
            raise ProtocolError('translation_derivation_link_required')
        try:ca,cb=contexts[a.record_id],contexts[b.record_id]
        except (KeyError,TypeError) as exc:raise ProtocolError('translation_source_context_required') from exc
        aa=verify_anchor(a,pair.original,ca['root']);bb=verify_anchor(b,pair.translated,cb['root'])
        def member(r):return {'record_id':r.record_id,'language':r.language,'input_hash':r.input_hash,'lineage_hash':digest(r.lineage)}
        out.append({'id':pair.id,'original':member(a),'translated':member(b),'original_anchor':aa,'translated_anchor':bb,
            'structure_id':x.structure_id,'component_id':x.component_id,'fact_root_ids':sorted(set(x.fact_root_ids)),
            'split':a.split,'executor':pair.executor.model_dump(mode='json'),'revision':pair.revision,
            'mechanical_source_check':'verified','semantic_translation_review':'pending','quality_verified':False})
    return {'protocol':'w07-translation-metadata-v1','pairs':out}


def language_report(records,annotations,metadata):
    rows=list(records);labels={a.record_id:a for a in annotations};paired={m['record_id'] for p in metadata['pairs'] for m in [p['original'],p['translated']]}
    report={}
    for lang in LANGUAGES:
        subset=[r for r in rows if r.language==lang]
        report[lang]={'status':'present_mechanical_only' if subset else 'blocked_missing_language_data','records':len(subset),
            'record_ids':[r.record_id for r in subset],'sources':dict(Counter(r.bucket for r in subset)),
            'accepted_label_tiers':dict(Counter(labels[r.record_id].label_tier for r in subset if labels[r.record_id].status=='accepted')),
            'annotation_status':dict(Counter(labels[r.record_id].status for r in subset)),
            'evaluable':sum(bool(labels[r.record_id].final and labels[r.record_id].final.evidence_evaluable) for r in subset),
            'label_only':sum(bool(labels[r.record_id].final and not labels[r.record_id].final.evidence_evaluable) for r in subset),
            'structures':len({r.lineage.structure_id for r in subset}),'unpaired_record_ids':[r.record_id for r in subset if r.record_id not in paired],
            'semantic_quality':'not_validated'}
    return {'required_languages':list(LANGUAGES),'languages':report,'translation_pairs':len(metadata['pairs']),
        'unknown_language_record_ids':[r.record_id for r in rows if r.language not in LANGUAGES],
        'independent_structures':len({r.lineage.structure_id for r in rows}),'translation_rows_are_not_independent_structures':True,
        'bilingual_quality_ready':False,'remaining':['real bilingual source/translation review','language-specific gold and model/product evaluation']}
