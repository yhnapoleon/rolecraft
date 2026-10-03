import json
from collections import Counter
import pytest

from career_lab.datasets.controlled import generate_controlled, verify_row, build_controlled_release
from career_lab.datasets.annotation import export_annotation_pack, import_annotations
from career_lab.datasets.release import audit_release


def test_generation_balanced_verified_and_not_single_evidence():
    rows = generate_controlled(roots_per_template=2)
    assert len(rows) == 288
    assert Counter(r['gold']['label'] for r in rows) == {k:96 for k in ('SUPPORTED','CONTRADICTED','INSUFFICIENT')}
    assert all(verify_row(r) for r in rows)
    assert all(len(r['input']['candidate_evidence']) >= 5 for r in rows)
    assert all('尚未提供' not in json.dumps(r['input'],ensure_ascii=False) for r in rows)
    assert len({tuple(e['id'] for e in r['input']['candidate_evidence']) for r in rows}) > 1
    damaged = json.loads(json.dumps(rows[0]))
    damaged['gold']['label'] = 'INSUFFICIENT'
    assert not verify_row(damaged)


def test_release_proof_audit_and_blind_annotation(tmp_path):
    rows = generate_controlled(roots_per_template=1)
    path = build_controlled_release(tmp_path/'data', rows)
    assert audit_release(path)['samples'] == 144
    pack = export_annotation_pack(path, tmp_path/'annotation', count=30)
    assert pack['items'] == 30 and pack['human_status']=='pending'
    raw = (tmp_path/'annotation'/'annotator-a.csv').read_text(encoding='utf-8-sig')
    assert 'SUPPORTED' not in raw and 'verifier' not in raw
    result = import_annotations(tmp_path/'annotation', tmp_path/'annotation'/'annotator-a.csv', tmp_path/'annotation'/'annotator-b.csv')
    assert result['status']=='pending' and result['kappa'] is None
    assert all(x['split']!='test' for x in pack['selection'])


def test_annotation_rejects_unlisted_evidence(tmp_path):
    import csv
    manifest=build_controlled_release(tmp_path/'data',generate_controlled(1))
    export_annotation_pack(manifest,tmp_path/'pack',count=1)
    for name,person in [('annotator-a.csv','a'),('annotator-b.csv','b')]:
        p=tmp_path/'pack'/name
        with p.open(encoding='utf-8-sig',newline='') as f: entries=list(csv.DictReader(f))
        entries[0].update(annotator_id=person,label='SUPPORTED',evidence_sets='[["missing"]]',minutes='1')
        with p.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=entries[0]);w.writeheader();w.writerows(entries)
    with pytest.raises(ValueError,match='evidence'):
        import_annotations(tmp_path/'pack',tmp_path/'pack'/'annotator-a.csv',tmp_path/'pack'/'annotator-b.csv')


def test_proof_rejects_changed_claim_or_missing_requirement():
    from career_lab.contracts.evaluation import EvidencePackage
    from career_lab.evidence.serializer import seal_input
    row=generate_controlled(1)[0]
    changed=json.loads(json.dumps(row))
    changed['input']=seal_input(EvidencePackage.model_validate(changed['input']).model_copy(update={'claim':changed['input']['claim'].replace('该条件成立','该条件不成立')})).model_dump(mode='json')
    assert not verify_row(changed)
    unknown=next(r for r in generate_controlled(1) if r['gold']['label']=='INSUFFICIENT')
    unknown['gold']['missing_requirement']='unrelated'
    assert not verify_row(unknown)


def test_annotation_rejects_changed_display_with_old_hash(tmp_path):
    import csv
    manifest=build_controlled_release(tmp_path/'data',generate_controlled(1))
    export_annotation_pack(manifest,tmp_path/'pack',count=1)
    p=tmp_path/'pack'/'annotator-a.csv'
    with p.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    rows[0]['claim']='different claim'
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
    with pytest.raises(ValueError,match='display'):
        import_annotations(tmp_path/'pack',p,tmp_path/'pack'/'annotator-b.csv')
