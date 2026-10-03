from fastapi.testclient import TestClient
from career_lab.api.app import create_app
from career_lab.datasets.controlled import generate_controlled,build_controlled_release
from career_lab.models.training import train_baselines
from career_lab.experiments.study import run_development,freeze_study,run_confirmatory


def test_shadow_is_authenticated_versioned_and_never_scores(tmp_path):
    manifest=build_controlled_release(tmp_path/'data',generate_controlled(1))
    models=tmp_path/'models';train_baselines(manifest,models)
    study=tmp_path/'study';run_development(manifest,models,study);freeze_study(manifest,models,study);run_confirmatory(study)
    app=create_app(f"sqlite:///{tmp_path/'app.db'}",study_path=study)
    client=TestClient(app);session=client.post('/sessions',json={}).json();sid=session['session_id']
    url=f'/sessions/{sid}/relation-checks';body={'claim':'50人试点符合当前容量要求。','request_id':'r1'}
    assert client.post(url,json=body).status_code==401
    headers={'Authorization':'Bearer '+session['token']}
    before=app.state.store.get_state(sid)
    reply=client.post(url,json=body,headers=headers)
    assert reply.status_code==200,reply.text
    data=reply.json()
    assert data['mode']=='shadow' and data['review_required'] is True
    assert data['affects_score'] is False and data['freeze_id']
    assert app.state.store.get_state(sid)==before
    assert client.post(url,json=body,headers=headers).json()==data
    assert client.post(url,json={**body,'claim':'changed'},headers=headers).status_code==409
    assert all(s['object_id']!='tech_private' for s in data['sources'].values())
    assert all(s['version']!=2 for s in data['sources'].values())


def test_shadow_unconfigured_explicit(tmp_path):
    client=TestClient(create_app(f"sqlite:///{tmp_path/'app.db'}"))
    s=client.post('/sessions',json={}).json()
    assert client.post(f"/sessions/{s['session_id']}/relation-checks",json={'claim':'claim','request_id':'r1'},headers={'Authorization':'Bearer '+s['token']}).status_code==503
