"""Consumer P2 probes; no research-data authenticity is inferred from these doubles."""
from dataclasses import replace
import json
import numpy as np
import pytest
from test_w08_models import examples,release_fixture
from career_lab.contracts.v2.core import FileRef,digest,ProtocolError
from career_lab.contracts.v2.data import AnnotationV2
from career_lab.models.v3.core import evidence_target,Prediction
from career_lab.models.v3.linear import LinearCandidate
from career_lab.models.v3.encoder import AttentionEncoder
from career_lab.models.v3.bundle import json_bytes,sha
from career_lab.experiments.v3.training.metrics import grade,summarize
from career_lab.experiments.v3.training.data import ReleaseReader,RecordReadError


def label_only(row):
    raw=row.annotation.model_dump(mode='json');raw['final'].update(evidence_ids=[],acceptable_evidence_sets=[],evidence_evaluable=False)
    return replace(row,annotation=AnnotationV2.model_validate_json(AnnotationV2.model_validate(raw).model_dump_json()))


def test_label_only_has_zero_evidence_gradient_no_pairs_and_no_metric_denominator():
    rows=examples();rows[0]=label_only(rows[0]);row=rows[0];assert row.annotation.final.label=='SUPPORTED'
    assert evidence_target(row) is None
    linear=LinearCandidate();report=linear.fit(rows)
    assert report['evidence_pairs']==10 and report['label_only_train_ids']==[row.record_id] and row.record_id not in report['evidence_train_ids']
    for variant in ['pack','pair']:
        model=AttentionEncoder(variant=variant,dimension=4);model.initialize(rows);loss,grad=model.loss_and_grad(row)
        assert np.count_nonzero(grad['evidence'])==0 and np.count_nonzero(grad['evidence_bias'])==0
        assert np.linalg.norm(grad['relation'])>0
    values=[grade(r,linear.predict(r.item)) for r in rows];summary=summarize(values,'relation')
    assert summary['count']==6 and summary['evidence_denominator']==summary['joint_denominator']==5
    failed=grade(row,Prediction('relation',row.annotation.input_hash,'fixture','failed',None,None,reason_code='fixture_failure'))
    assert failed['evidence_f1'] is None and failed['joint_correct'] is None


@pytest.mark.parametrize('task,label',[('relation','SUPPORTED'),('relation','INSUFFICIENT'),('criterion','MET'),('criterion','NOT_APPLICABLE')])
def test_evidence_target_uses_validated_acceptable_sets(task,label):
    row=next(r for r in examples(task=task) if r.annotation.final.label==label);raw=row.annotation.model_dump(mode='json')
    raw['final'].update(evidence_ids=['e2'],acceptable_evidence_sets=[['e1']],evidence_evaluable=True)
    wrong=replace(row,annotation=AnnotationV2.model_validate(raw))
    with pytest.raises(ProtocolError,match='acceptable_target'):evidence_target(wrong)
    raw['final']['acceptable_evidence_sets']=[['e2'],['e1']];valid=replace(row,annotation=AnnotationV2.model_validate(raw))
    assert evidence_target(valid)=={'e1'}  # canonical minimum target; final may choose another legal alternative


@pytest.mark.parametrize('rewrite_snapshot_and_origin',[False,True])
def test_laundered_fixture_cannot_be_blessed_by_rehashed_metadata(tmp_path,rewrite_snapshot_and_origin):
    root=tmp_path/'data';release,split=release_fixture(root);manifest=json.loads((root/'manifest.json').read_text());split_data=json.loads((root/'split-manifest.json').read_text())
    # Simulate an adversary rewriting all outer hashes and six structure declarations.
    for index,entry in enumerate(split_data['entries']):
        rid=entry['record_id'];entry['structure_id']=entry['split']+'-'+str(index%2)
        path=root/f'metadata/{rid}.json';meta=json.loads(path.read_text());meta['lineage']['structure_id']=entry['structure_id'];meta['bucket']='env_run';meta['provenance']['transformations']=[]
        if rewrite_snapshot_and_origin:meta['source_snapshots'][0]['origin']='env_run'
        path.write_bytes(json_bytes(meta));manifest['files'][path.relative_to(root).as_posix()]=sha(path.read_bytes())
        if rewrite_snapshot_and_origin:
            op=root/f'origins/{rid}.json';origin=json.loads(op.read_text());origin.update(origin='env_run',lineage_hash=digest(meta['lineage']));op.write_bytes(json_bytes(origin));manifest['files'][op.relative_to(root).as_posix()]=sha(op.read_bytes())
    split_data['independent_structure_count']=6;(root/'split-manifest.json').write_bytes(json_bytes(split_data));manifest['files']['split-manifest.json']=sha((root/'split-manifest.json').read_bytes())
    idx=json.loads((root/'record-metadata.json').read_text())
    for rid,ref in idx['records'].items():ref['sha256']=manifest['files'][ref['path']]
    (root/'record-metadata.json').write_bytes(json_bytes(idx));manifest['metadata']['sha256']=manifest['files']['record-metadata.json']=sha((root/'record-metadata.json').read_bytes())
    manifest['fixture']=False;manifest['id']=digest({k:v for k,v in manifest.items() if k!='id'});(root/'manifest.json').write_bytes(json_bytes(manifest))
    reader=ReleaseReader(root,FileRef(path='manifest.json',sha256=sha((root/'manifest.json').read_bytes())),FileRef(path='split-manifest.json',sha256=manifest['files']['split-manifest.json']),metadata_approval=lambda *args:None)
    with pytest.raises(RecordReadError) as exc:reader.load('train')
    assert exc.value.cause_code==('independent_source_authority_required' if rewrite_snapshot_and_origin else 'ValidationError')
