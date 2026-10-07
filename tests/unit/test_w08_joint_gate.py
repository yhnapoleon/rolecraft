"""Joint-candidate eligibility and reader bookkeeping on declared schema fixtures."""
from dataclasses import replace
from pathlib import Path
import json
import pytest
from test_w08_models import examples,release_fixture
from test_w08_boundaries import label_only
from career_lab.contracts.v2.core import FileRef,ProtocolError,digest
from career_lab.contracts.v2.data import RelationInput
from career_lab.contracts.v2.evaluation import EvidencePackageV2
from career_lab.models.v3.core import training_examples
from career_lab.models.v3.linear import LinearCandidate
from career_lab.models.v3.legacy import LegacyMLP
from career_lab.models.v3.encoder import AttentionEncoder
from career_lab.models.v3.bundle import json_bytes,sha
from career_lab.experiments.v3.training.data import ReleaseReader,RecordReadError
from career_lab.experiments.v3.training.pipeline import run_development


FACTORIES=[LinearCandidate,LegacyMLP,lambda:AttentionEncoder(variant='pack',dimension=4),lambda:AttentionEncoder(variant='pair',dimension=4),lambda:AttentionEncoder(variant='pair',aggregation='mean_logits',dimension=4)]


def changed_input(row,change):
    raw=row.item.evidence.model_dump(mode='json',exclude={'input_hash'});change(raw)
    item=RelationInput(evidence=EvidencePackageV2(**raw,input_hash=digest(raw)))
    return replace(row,item=item,annotation=row.annotation.model_copy(update={'input_hash':digest(item)}))


@pytest.mark.parametrize('factory',FACTORIES)
def test_all_label_only_train_rejected_before_fitting(factory):
    rows=[label_only(r) for r in examples()];model=factory()
    with pytest.raises(ProtocolError) as exc:model.fit(rows)
    assert exc.value.code=='joint_training_evidence_required' and exc.value.split=='train'
    assert exc.value.report['record_ids']==[r.record_id for r in rows]
    assert not any(hasattr(model,name) for name in ['params','coef','coefs','training_report'])


@pytest.mark.parametrize('factory',FACTORIES)
def test_one_legal_evaluable_train_row_is_minimum_not_a_quality_claim(factory):
    rows=examples();rows=[rows[0],*[label_only(r) for r in rows[1:]]]
    model=factory();report=model.fit(rows,epochs=1) if isinstance(model,AttentionEncoder) else model.fit(rows)
    assert report['fit_seconds']>0
    assert training_examples([label_only(r) for r in examples('dev',1)],'relation',split='dev',require_all_classes=False)


@pytest.mark.parametrize('factory',FACTORIES)
def test_direct_fit_incomplete_has_record_split_and_reason(factory):
    rows=examples();rows[0]=changed_input(rows[0],lambda raw:raw.update(completeness='missing'))
    with pytest.raises(ProtocolError) as exc:factory().fit(rows)
    assert exc.value.record_id==rows[0].record_id and exc.value.split=='train'
    assert exc.value.report=={'record_id':rows[0].record_id,'split':'train','reason':'input_missing'}


@pytest.mark.parametrize('variant',['pack','pair'])
def test_capacity_filter_cannot_remove_only_evaluable_row_and_leave_untrained_head(variant):
    rows=[label_only(r) for r in examples()]
    extra=replace(examples()[0],record_id='long-only-evaluable',annotation=examples()[0].annotation.model_copy(update={'record_id':'long-only-evaluable'}))
    extra=changed_input(extra,lambda raw:raw['candidate_evidence'][0].update(text='capacity evidence '*1000))
    model=AttentionEncoder(variant=variant,dimension=4,max_tokens=128)
    with pytest.raises(ProtocolError) as exc:model.fit([*rows,extra],epochs=1)
    assert exc.value.code=='joint_training_evidence_required'
    assert exc.value.report['reason']=='joint_training_evidence_required' and exc.value.report['kept_train_records']==6
    assert exc.value.report['excluded_records'][0]['record_id']==extra.record_id
    assert not hasattr(model,'params')


def rewrite_labels(root,ids,*,invalid=False):
    m=json.loads((root/'manifest.json').read_text())
    for rid in ids:
        name=f'labels/{rid}.json';p=root/name;a=json.loads(p.read_text());a['final'].update(evidence_evaluable=False,evidence_ids=[],acceptable_evidence_sets=[['e1','e1']] if invalid else [])
        p.write_bytes(json_bytes(a));m['files'][name]=sha(p.read_bytes())
    m['id']=digest({k:v for k,v in m.items() if k!='id'});(root/'manifest.json').write_bytes(json_bytes(m))
    return FileRef(path='manifest.json',sha256=sha((root/'manifest.json').read_bytes()))


def test_label_only_reader_legal_but_pipeline_rejects_before_dev_or_bundle(tmp_path):
    root=tmp_path/'data';release,split=release_fixture(root);ids=[r.record_id for r in examples()];release=rewrite_labels(root,ids)
    reader=ReleaseReader(root,release,split,allow_fixture=True);rows=reader.load('train')
    assert len(rows)==6 and all(not r.annotation.final.evidence_evaluable for r in rows)
    out=tmp_path/'run'
    with pytest.raises(ProtocolError) as exc:run_development(reader,out,workspace=Path(__file__).resolve().parents[2],epochs=1,dimension=4)
    assert exc.value.code=='joint_training_evidence_required'
    assert not any(a['purpose'].startswith('dev:') for a in reader.access_log)
    assert not (out/'models').exists() and not (out/'freeze.json').exists() and not (out/'reports/development.json').exists()
    assert json.loads((out/'failure.json').read_text())['details']['evaluable_records']==0


def test_label_only_statistics_are_idempotent_and_only_after_full_row_validation(tmp_path):
    root=tmp_path/'data';release,split=release_fixture(root);ids=[examples()[0].record_id,examples('dev',1)[0].record_id];release=rewrite_labels(root,ids)
    reader=ReleaseReader(root,release,split,allow_fixture=True)
    for _ in range(2):reader.load('train');reader.load('dev')
    stats=reader.scope_report()['label_only_records'];assert len(stats)==2
    assert {(x['release_sha256'],x['partition'],x['record_id']) for x in stats}=={(release.sha256,'train',ids[0]),(release.sha256,'dev',ids[1])}
    bad=tmp_path/'bad';release2,split2=release_fixture(bad);rid=examples()[0].record_id;release2=rewrite_labels(bad,[rid],invalid=True)
    denied=ReleaseReader(bad,release2,split2,allow_fixture=True)
    with pytest.raises(RecordReadError) as exc:denied.load('train')
    assert exc.value.record_id==rid and exc.value.cause_code=='training_gold_duplicate_reference'
    assert denied.label_only_records==[]


@pytest.mark.parametrize('attack',['structure','component','ancestor'])
def test_existing_split_manifest_isolation_rejects_at_reader_before_any_body(tmp_path,monkeypatch,attack):
    root=tmp_path/'data';release,split=release_fixture(root);s=json.loads((root/'split-manifest.json').read_text());train=next(e for e in s['entries'] if e['split']=='train');test=next(e for e in s['entries'] if e['split']=='test')
    if attack=='ancestor':test['ancestors']=[train['record_id']]
    else:test[attack+'_id']=train[attack+'_id']
    (root/'split-manifest.json').write_bytes(json_bytes(s));m=json.loads((root/'manifest.json').read_text());m['files']['split-manifest.json']=sha((root/'split-manifest.json').read_bytes());m['id']=digest({k:v for k,v in m.items() if k!='id'});(root/'manifest.json').write_bytes(json_bytes(m))
    release=FileRef(path='manifest.json',sha256=sha((root/'manifest.json').read_bytes()));split=FileRef(path='split-manifest.json',sha256=m['files']['split-manifest.json'])
    original=Path.read_bytes;opened=[]
    def guard(path,*a,**kw):
        name=path.relative_to(root).as_posix();opened.append(name)
        assert name in ['manifest.json','split-manifest.json'],'body opened before isolation'
        return original(path,*a,**kw)
    monkeypatch.setattr(Path,'read_bytes',guard)
    with pytest.raises(ValueError,match='split'):ReleaseReader(root,release,split,allow_fixture=True)
    assert opened==['manifest.json','split-manifest.json']



def test_linear_still_rejects_single_class_evidence_pairs_after_global_minimum():
    from career_lab.models.v3.core import evidence_target
    original=examples();only=next(r for r in original if r.annotation.final.label=='INSUFFICIENT')
    rows=[r if r.record_id==only.record_id else label_only(r) for r in original]
    assert training_examples(rows,'relation') and evidence_target(only)==set()
    assert {int(c.id in evidence_target(only)) for c in only.item.evidence.candidate_evidence}=={0}
    with pytest.raises(ProtocolError) as exc:LinearCandidate().fit(rows)
    assert exc.value.code=='evidence_selector_class_coverage_missing'
