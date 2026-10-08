"""Synthetic bilingual mechanics only; no real translation/model quality claim."""
from dataclasses import replace
import hashlib
import pytest
from test_w07_pipeline import make_case
from career_lab.contracts.v2.core import FileRef, ProtocolError, digest
from career_lab.contracts.v2.data import DatasetRecordV2
from career_lab.datasets.v3.export import export_snapshot
from career_lab.datasets.v3.bilingual import TextAnchor, TranslationPair, verify_pairs, pair_dict, read_pairs, language_report, PROTOCOL


def paired(tmp_path):
    snapshot, units, _ = make_case(tmp_path)
    result = export_snapshot(snapshot, [units[0]])
    original = result.records[0]
    rows = []
    anchors = []
    for lang, quote in [('zh', '容量不超过三十人'), ('en', 'Capacity is at most thirty people')]:
        p = tmp_path / (lang + '.txt'); p.write_text(quote)
        file = FileRef(path=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest(), media_type='text/plain')
        data = original.model_dump(mode='json')
        data['record_id'] = lang; data['language'] = lang
        evidence = data['model_input']['evidence']; evidence['claim'] = quote
        evidence['input_hash'] = digest({k:v for k,v in evidence.items() if k != 'input_hash'})
        data['input_hash'] = digest(data['model_input'])
        data['provenance']['actual_sources'].append(file.model_dump(mode='json'))
        data['lineage']['derivation_ids'] = ['synthetic-pair']
        if lang == 'en': data['lineage']['source_record_ids'] = ['zh']
        rows.append(DatasetRecordV2.model_validate(data))
        anchors.append(TextAnchor(file, ('evidence','claim'), 0, len(quote), quote))
    pair = TranslationPair('synthetic-pair', 'zh', 'en', *anchors, original.provenance.executor, 'unit-only-v1')
    return rows, pair, {r.record_id:{'root':tmp_path} for r in rows}


def test_pair_roundtrip_and_language_report(tmp_path):
    rows, pair, contexts = paired(tmp_path)
    meta = verify_pairs(rows, read_pairs({'protocol':PROTOCOL,'pairs':[pair_dict(pair)]}), contexts)
    assert meta['pairs'][0]['quality_verified'] is False
    assert meta['pairs'][0]['original_anchor']['quote_sha256'] == hashlib.sha256(pair.original.quote.encode()).hexdigest()
    from career_lab.contracts.v2.data import AnnotationV2
    labels = [AnnotationV2(record_id=r.record_id,input_hash=r.input_hash,annotation_version='fixture-pending',status='pending',label_tier='G2',passes=()) for r in rows]
    report = language_report(rows, labels, meta)
    assert report['independent_structures'] == 1 and not report['bilingual_quality_ready']
    assert [report['languages'][lang]['records'] for lang in ('zh','en')] == [1,1]
    assert all(report['languages'][lang]['annotation_status'] == {'pending':1} for lang in ('zh','en'))


@pytest.mark.parametrize('change,code', [('split','translation_cross_split'),('lineage','translation_causal_group_mismatch'),('link','translation_derivation_link_required')])
def test_pair_rejects_changed_group(tmp_path, change, code):
    rows, pair, contexts = paired(tmp_path); raw=rows[1].model_dump(mode='json')
    if change=='split':raw['split']='test'
    elif change=='lineage':raw['lineage']['component_id']='different'
    else:raw['lineage']['source_record_ids']=[]
    rows[1]=DatasetRecordV2.model_validate(raw)
    with pytest.raises(ProtocolError, match=code.replace("_", " ")): verify_pairs(rows,[pair],contexts)


@pytest.mark.parametrize('bad', ['span','quote','hidden','file'])
def test_pair_rejects_wrong_source_or_hidden_path(tmp_path,bad):
    rows,pair,contexts=paired(tmp_path)
    if bad=='span':pair=replace(pair,original=replace(pair.original,span_start=1))
    elif bad=='quote':pair=replace(pair,original=replace(pair.original,quote='wrong'))
    elif bad=='hidden':pair=replace(pair,original=replace(pair.original,text_path=('gold',)))
    else:(tmp_path/'zh.txt').write_text('changed bytes')
    with pytest.raises(ProtocolError):verify_pairs(rows,[pair],contexts)
