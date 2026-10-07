"""Synthetic fixed-weight bundle fixtures. No fitting or model-quality claim."""
from dataclasses import replace
import json
import shutil
import subprocess
import sys
import numpy as np
import pytest

from career_lab.contracts.v2.core import FileRef, SourceIdentity, ProtocolError, digest
from career_lab.models.v3.linear import LinearCandidate
from career_lab.models.v3.core import LABELS
from career_lab.models.v3.bundle import save_bundle, json_bytes, sha
from career_lab.models.v3.registry import register_bundle, load_registration, public_registration
from career_lab.models.v3.advisory import RegisteredAdvisory, to_public_prediction
from career_lab.experiments.v3.training.review import review_registered
from test_w08_models import examples


def fixture_bundle(tmp_path):
    config = {"preprocessing_revision":"historical-time-v1", "kind":"linear", "task_type":"relation",
              "seed":5002, "max_features":1, "vocabulary":{"a":0}, "evidence_threshold":.5,
              "labels":list(LABELS['relation']),
              "training_report":{"scope":"synthetic_fixed_weights", "fit_performed":False}}
    arrays = {"coef":np.zeros((3,1)), "intercept":np.array([2.,0.,-2.]),
              "evidence_coef":np.zeros(1), "evidence_intercept":np.zeros(1), "idf":np.ones(1)}
    model = LinearCandidate.restore(config, arrays)
    data = tmp_path/'source';data.mkdir()
    release = json_bytes({'fixture':True,'scope':'synthetic_fixed_weights_no_training'})
    split = json_bytes({'fixture':True,'scope':'synthetic_no_held_out_data'})
    (data/'release.json').write_bytes(release);(data/'split.json').write_bytes(split)
    ref = save_bundle(model,tmp_path/'bundle',source_root=data,
                      training_release=FileRef(path='release.json',sha256=sha(release)),
                      split_manifest=FileRef(path='split.json',sha256=sha(split)),
                      source=SourceIdentity(base_commit='a'*40,source_digest=digest('synthetic-no-fit')))
    return tmp_path/'bundle',ref


def registered(tmp_path):
    root,ref=fixture_bundle(tmp_path)
    registration=register_bundle(tmp_path/'registry',root,ref,scope='synthetic_fixture')
    return root,ref,registration


def test_registration_is_portable_immutable_and_only_advisory(tmp_path,monkeypatch):
    monkeypatch.setattr(LinearCandidate,'fit',lambda *a,**k:pytest.fail('registration must never train'))
    root,ref,r=registered(tmp_path)
    assert register_bundle(tmp_path/'registry',root,ref,scope='synthetic_fixture')==r
    shutil.move(tmp_path/'registry',tmp_path/'relocated')
    model,entry=load_registration(tmp_path/'relocated',r)
    (root/'weights/model.npz').write_bytes(b'producer directory changed after registration')
    same,again=load_registration(tmp_path/'relocated',r)
    assert entry==again and model.revision==same.revision
    public=public_registration(entry)
    assert public['mode']=='advisory' and public['affects_score'] is False
    assert public['quality_validated'] is False and public['scope']=='synthetic_fixture'
    assert 'files' not in public and 'bundle' not in public


def test_fixture_cannot_be_promoted_to_external_or_product(tmp_path):
    root,ref,r=registered(tmp_path)
    with pytest.raises(ProtocolError) as error:
        register_bundle(tmp_path/'other',root,ref,scope='external_candidate')
    assert error.value.code=='fixture_cannot_be_registered_as_external'
    adapter=RegisteredAdvisory(tmp_path/'registry',r,tmp_path/'journal')
    with pytest.raises(ProtocolError) as error:
        adapter.predict(examples('dev')[0].item,request_id='one',work_language='zh')
    assert error.value.code=='synthetic_model_not_product_ready'
    assert not (tmp_path/'journal').exists()


def test_registered_weight_tampering_is_rejected(tmp_path):
    _,_,r=registered(tmp_path)
    path=tmp_path/'registry'/r.path
    entry=json.loads(path.read_bytes())
    artifact=path.parent/'artifact'
    target=next(p for p in entry['files'] if p.endswith('.npz'))
    (artifact/target).write_bytes(b'changed bytes')
    with pytest.raises(ProtocolError):load_registration(tmp_path/'registry',r)


def test_registered_runtime_drift_is_rejected(tmp_path,monkeypatch):
    _,_,r=registered(tmp_path)
    import career_lab.models.v3.registry as registry
    monkeypatch.setattr(registry,'inference_runtime',lambda:{'source_digest':'0'*64,'dependencies':{}})
    with pytest.raises(ProtocolError) as error:load_registration(tmp_path/'registry',r)
    assert error.value.code=='registered_inference_runtime_changed'


def test_prediction_recovery_never_invokes_model_again(tmp_path,monkeypatch):
    _,_,r=registered(tmp_path);model,entry=load_registration(tmp_path/'registry',r)
    import career_lab.models.v3.advisory as advisory
    calls=[]
    class Spy:
        def predict(self,item):calls.append(digest(item));return model.predict(item)
    monkeypatch.setattr(advisory,'load_registration',lambda *a:(Spy(),entry))
    adapter=RegisteredAdvisory(tmp_path/'registry',r,tmp_path/'journal',allow_synthetic=True)
    row=examples('dev')[0]
    result=adapter.predict(row.item,request_id='once',work_language='en')
    assert result==adapter.recover('once')==adapter.predict(row.item,request_id='once',work_language='en')
    assert len(calls)==1 and result['prediction']['labels']==list(LABELS['relation'])
    assert result['semantic_status']=='synthetic_mechanism_only' and result['automatic_retries']==0
    assert 'gold' not in json.dumps(result) and 'model_input' not in json.dumps(result)
    with pytest.raises(ProtocolError) as error:adapter.predict(row.item,request_id='once',work_language='zh')
    assert error.value.code=='advisory_request_id_reused' and len(calls)==1


def test_failed_call_only_retries_on_explicit_new_identity(tmp_path,monkeypatch):
    _,_,r=registered(tmp_path);model,entry=load_registration(tmp_path/'registry',r)
    import career_lab.models.v3.advisory as advisory
    calls=[]
    class Flaky:
        def predict(self,item):
            calls.append(1)
            if len(calls)==1:raise TimeoutError('synthetic timeout')
            return model.predict(item)
    monkeypatch.setattr(advisory,'load_registration',lambda *a:(Flaky(),entry))
    adapter=RegisteredAdvisory(tmp_path/'registry',r,tmp_path/'journal',allow_synthetic=True);item=examples('dev')[0].item
    failed=adapter.predict(item,request_id='first',work_language='zh')
    assert failed['status']=='failed' and failed['failure_kind']=='infrastructure' and failed['prediction'] is None
    assert adapter.predict(item,request_id='first',work_language='zh')==failed and len(calls)==1
    ok=adapter.predict(item,request_id='explicit-retry',work_language='zh',retry_of='first')
    assert ok['status']=='completed' and ok['retry_of']=='first' and len(calls)==2
    assert adapter.recover('first')==failed


def test_interrupted_pending_is_not_automatically_recalled(tmp_path,monkeypatch):
    _,_,r=registered(tmp_path)
    adapter=RegisteredAdvisory(tmp_path/'registry',r,tmp_path/'journal',allow_synthetic=True);item=examples('dev')[0].item
    path=adapter._path('interrupted');path.mkdir(parents=True)
    binding={'request_id':'interrupted','input_hash':digest(item),'registration':r.model_dump(mode='json'),'work_language':'en','retry_of':None}
    (path/'request.json').write_bytes(json_bytes(binding))
    import career_lab.models.v3.advisory as advisory
    monkeypatch.setattr(advisory,'load_registration',lambda *a:pytest.fail('recovery must not load/call a model'))
    assert adapter.predict(item,request_id='interrupted',work_language='en')['status']=='unconfirmed'


def test_bilingual_recomputation_and_producer_comparison_use_joint_metric(tmp_path):
    _,_,r=registered(tmp_path)
    rows=[replace(row,language='zh' if i%2 else 'en') for i,row in enumerate(examples('dev'))]
    result=review_registered(tmp_path/'registry',r,rows)
    assert result['reload_predictions_identical'] and not result['training_performed']
    assert result['producer_comparison']['status']=='not_supplied'
    assert result['metrics']['count']==6 and result['metrics']['macro_f1']==pytest.approx(1/6)
    assert result['metrics']['joint_correctness']==0
    for lang in ('zh','en'):assert result['languages'][lang]['metrics']['count']==3
    assert not result['quality_validated']
    same=review_registered(tmp_path/'registry',r,rows,producer_predictions=result['predictions'])
    assert same['producer_comparison']['status']=='matched'
    changed=json.loads(json.dumps(result['predictions']));changed[0]['prediction'].update(label='CONTRADICTED',probabilities=[0,1,0])
    mismatch=review_registered(tmp_path/'registry',r,rows,producer_predictions=changed)
    assert mismatch['producer_comparison']['mismatched_record_ids']==[rows[0].record_id]


def test_review_rejects_label_order_and_held_out_campaign(tmp_path):
    _,_,r=registered(tmp_path);rows=examples('dev');out=review_registered(tmp_path/'registry',r,rows)
    assert out['languages']['zh']['status']=='blocked_missing_language'
    out['predictions'][0]['prediction']['labels'].reverse()
    with pytest.raises(ProtocolError) as error:review_registered(tmp_path/'registry',r,rows,producer_predictions=out['predictions'])
    assert error.value.code=='review_producer_label_or_mode_mismatch'
    with pytest.raises(ProtocolError) as error:review_registered(tmp_path/'registry',r,[replace(rows[0],split='test')])
    assert error.value.code=='review_held_out_campaign_required'


def test_review_technical_failures_are_not_insufficient_and_not_retried(tmp_path,monkeypatch):
    _,_,r=registered(tmp_path);_,entry=load_registration(tmp_path/'registry',r)
    import career_lab.experiments.v3.training.review as review
    calls=[]
    class Broken:
        def predict(self,item):calls.append(1);raise TimeoutError('synthetic only')
    monkeypatch.setattr(review,'load_registration',lambda *a:(Broken(),entry))
    result=review.review_registered(tmp_path/'registry',r,examples('dev'))
    assert len(calls)==6 and result['metrics']['infrastructure_failures']==6
    assert not result['reload_predictions_identical']
    assert all(p['prediction']['label'] is None for p in result['predictions'])


def test_fixture_public_projection_remains_unavailable(tmp_path):
    _,_,r=registered(tmp_path);item=examples('dev')[0].item
    adapter=RegisteredAdvisory(tmp_path/'registry',r,tmp_path/'journal',allow_synthetic=True)
    result=adapter.predict(item,request_id='projection',work_language='zh')
    projected=to_public_prediction(result,item)
    assert projected.status=='unavailable' and projected.probabilities is None
    assert projected.error_code=='synthetic_model_not_product_ready'
    assert tuple(projected.labels)==LABELS['relation']
    with pytest.raises(ProtocolError):to_public_prediction(result,examples('dev')[1].item)


def test_actual_registry_cli_registers_predicts_and_recovers_without_fit(tmp_path):
    root,ref=fixture_bundle(tmp_path);registry=tmp_path/'registry with spaces'
    def cli(*args):
        result=subprocess.run([sys.executable,'-m','career_lab.models.v3.registry_cli',*map(str,args)],capture_output=True,text=True)
        assert result.returncode==0,result.stdout+result.stderr
        return json.loads(result.stdout)
    entry=cli('register','--registry',registry,'--bundle-root',root,'--bundle-hash',ref.sha256,'--scope','synthetic_fixture')
    reg=entry['registration'];item=examples('dev')[0].item;input_path=tmp_path/'allowed-input.json';input_path.write_bytes(json_bytes(item))
    common=['--registry',registry,'--registration-path',reg['path'],'--registration-hash',reg['sha256'],'--journal',tmp_path/'journal','--request-id','cli-once']
    result=cli('predict',*common,'--input',input_path,'--language','en','--allow-synthetic')
    assert result['public_prediction']['status']=='unavailable'
    assert result==cli('recover',*common)
    assert result['automatic_retries']==0 and result['status']=='completed'


def test_null_producer_result_is_preserved_as_missing_not_agreement(tmp_path):
    _,_,r=registered(tmp_path);rows=examples('dev')
    producer=review_registered(tmp_path/'registry',r,rows)['predictions']
    producer[0]['prediction']=None
    result=review_registered(tmp_path/'registry',r,rows,producer_predictions=producer)
    assert result['producer_comparison']['status']=='incomplete'
    assert result['producer_comparison']['missing_prediction_record_ids']==[rows[0].record_id]
    assert result['predictions'][0]['prediction']['label']=='SUPPORTED'
    with pytest.raises(ProtocolError) as error:
        review_registered(tmp_path/'registry',r,rows,producer_predictions={'predictions':producer})
    assert error.value.code=='review_producer_records_invalid'
