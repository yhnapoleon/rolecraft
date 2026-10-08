"""Normal HTTP reads after a scenario upgrade and actual W04 counteroffer effects."""
from pathlib import Path
import json
from fastapi.testclient import TestClient
from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts import v2 as C
from test_w14_vertical_runtime import connect


def test_old_binding_is_readable_immutable_and_cannot_mutate(tmp_path,monkeypatch):
    monkeypatch.setenv('CAREER_LAB_SCENARIO_ARCHIVE',str(tmp_path/'archive'))
    root=Path(json.loads(Path('scenarios/pm_pilot/v2/installed/current.json').read_text())['main']['zh']['root']);old=tmp_path/'old';old.mkdir()
    bundle=C.ScenarioBundle.model_validate_json((root/'manifest.json').read_bytes())
    for ref in bundle.files:
        target=old/ref.path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(C.read_file(root,ref))
    runtime=C.RuntimeBundle.model_validate_json((old/'runtime/bundle.json').read_bytes()).model_copy(update={'revision':'previous-recorded-runtime'})
    (old/'runtime/bundle.json').write_text(runtime.model_dump_json(indent=2)+'\n')
    import hashlib
    bundle=bundle.model_copy(update={'files':tuple(ref.model_copy(update={'sha256':hashlib.sha256((old/ref.path).read_bytes()).hexdigest()}) for ref in bundle.files)})
    (old/'manifest.json').write_text(bundle.model_dump_json(indent=2)+'\n')
    db='sqlite:///'+str(tmp_path/'history.db');app=create_runtime_app(db,scenario_root=old);client=TestClient(app)
    created=client.post('/sessions',json={'schema_version':2,'scenario':'pm_pilot_v2','work_language':'zh'}).json();sid=created['session_id'];h={'Authorization':'Bearer '+created['token']}
    def send(path,key,operation,payload):
        state=client.get('/sessions/'+sid,headers=h).json()['state'];return client.post('/sessions/'+sid+'/'+path,headers=h,json={'schema_version':2,'request_id':key,'expected_version':state['business_seq'],'expected_workspace_revision':state['workspace_revision'],'operation':operation,'payload':payload})
    made=send('work-products','old-work','work_products.create',{'kind':'text','title':'原方案','content':'暂缓后继续调查，不改写这段原文。'})
    assert made.status_code==200,made.text
    product=next(ref for ref in made.json()['objects'] if ref['kind']=='product')
    read=send('actions','old-read','read_material',{'tool':'read_material','material':{'session_id':sid,'kind':'material','object_id':'brief','version':1}})
    assert read.status_code==200,read.text
    turn=send('turns','old-turn','turns.create',{'role_id':'supervisor','text':'请说明当前试点责任','shares':[]});assert turn.status_code==200,turn.text
    from career_lab.jobs.worker import Worker
    worker=Worker(app.state.jobs,app.state.handlers);assert worker.run_once()
    submission=send('submissions','old-submit','submissions.create',{'products':[product],'decision':'defer_with_conditions'});assert submission.status_code==200,submission.text
    assert worker.run_once()
    subject=submission.json()['result']['submission']['object_id']
    old_feedback=client.get('/sessions/'+sid+'/feedback/'+subject,headers=h).json()
    assert old_feedback['result']['result']['items']
    old_submissions=client.get('/sessions/'+sid+'/submissions',headers=h).json()
    before=client.get('/sessions/'+sid+'/work-products',headers=h).json()
    old_hash=created['binding']['scenarioHash'];app.state.store.close()
    app=create_runtime_app(db);client=TestClient(app)
    try:
        context=client.get('/sessions/'+sid+'/workbench',headers=h);assert context.status_code==200,context.text
        body=context.json()['result']['result'];assert body['read_only'] and body['session']['scenarioHash']==old_hash
        assert not body['available']['work_products.create'] and body['available']['work_products.list']
        assert client.get('/sessions/'+sid+'/work-products',headers=h).json()==before
        assert client.get('/sessions/'+sid+'/feedback/'+subject,headers=h).json()==old_feedback
        assert client.get('/sessions/'+sid+'/submissions',headers=h).json()==old_submissions
        assert any(row['ref']['kind']=='role_reply' for row in body['timeline']['objects'])
        original=client.get('/sessions/'+sid+'/objects/product/'+product['object_id']+'/1',headers=h);assert original.status_code==200,original.text
        assert original.json()['content']['content']=='暂缓后继续调查，不改写这段原文。'
        material=client.get('/sessions/'+sid+'/objects/material/brief/1',headers=h);assert material.status_code==200,material.text
        assert material.json()['content']['fragments'] and 'fact_ids' not in json.dumps(material.json())
        denied=send('work-products','no-new','work_products.create',{'kind':'text','title':'不能写','content':'blocked'})
        assert denied.status_code==409 and denied.json()['code']=='scenario_read_only'
        assert client.get('/sessions/'+sid+'/work-products',headers=h).json()==before
    finally:app.state.store.close()


def test_standard_counteroffer_keeps_original_request_and_grants_only_after_accept(tmp_path):
    app,c,sid,h,send=connect(tmp_path)
    try:
        config=app.state.scenario_v2.package.baseline(sid)
        base=C.ObjectRef(session_id=sid,kind='config',object_id=config.id,version=config.version,config_version=config.config_version).model_dump(mode='json')
        send('configuration','need50','configuration.apply',{'base':base,'settings':{'participants':50,'work_items':['scope_filter','human_fallback'],'fallback':'human'}})
        request=send('actions','request100','request_business',{'tool':'request_business','terms':{'capacity':100},'reason':'分批覆盖50人，需要容量与人工兜底。'})['result']['request']
        offered=send('approvals/resolve','check100','resolve_approval',{'request':request,'expected_request_revision':1})
        assert offered['result']['decision']['status']=='countered',offered
        assert c.get('/sessions/'+sid+'/timeline',headers=h).json()['result']['result']['workspace']['resources']['capacity']==30
        accepted=send('actions','accept60','accept_counteroffer',{'tool':'accept_counteroffer','request':offered['result']['request'],'terms':{'capacity':60}})
        assert c.get('/sessions/'+sid+'/timeline',headers=h).json()['result']['result']['workspace']['resources']['capacity']==60
        timeline=c.get('/sessions/'+sid+'/timeline',headers=h).json()['result']['result']
        requests=[r['content'] for r in timeline['objects'] if r['ref']['kind']=='business_request']
        assert all(r['requested']=={'capacity':100} for r in requests)
        assert any(r['status']=='accepted' for r in requests)
        made=send('work-products','approval-note','work_products.create',{'kind':'text','title':'按实际批准决定','content':'已接受60人容量，尚未上线。'})
        product=next(r for r in made['objects'] if r['kind']=='product')
        submitted=send('submissions','after-approval','submissions.create',{'decision':'defer_with_conditions','products':[product]})
        from career_lab.jobs.worker import Worker
        assert Worker(app.state.jobs,app.state.handlers).run_once()
        report=c.get('/sessions/'+sid+'/feedback/'+submitted['result']['submission']['object_id'],headers=h).json()['result']['result']['items'][0]
        assert '已接受' in report['business_response'] and '60' in report['business_response'] and '100' in report['business_response']

    finally:app.state.store.close()
