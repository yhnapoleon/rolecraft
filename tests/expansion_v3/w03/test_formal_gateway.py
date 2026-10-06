"""Actual Gateway + V2Store, synthetic registration only; no bypass router."""
from datetime import datetime,timezone,timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry,ScenarioRegistration
from career_lab.contracts.v2 import SessionBindings,FileRef,AssistantConfig
from career_lab.workspace.extension import install_workspace_operations


@pytest.fixture
def api(tmp_path):
    registry=ExtensionRegistry();file=FileRef(path='synthetic.json',sha256='1'*64)
    registry.register_scenario('w03-contract-fixture',ScenarioRegistration(SessionBindings(scenario=file,runtime=file,evaluation=file),AssistantConfig(id='config',session_id='fixture',domains=('stable_faq',)),{'capacity':30,'dev_days':3}))
    install_workspace_operations(registry,roles=('supervisor','business_lead','tech_lead'))
    app=create_app(f'sqlite:///{tmp_path / "formal.db"}',extensions=registry);client=TestClient(app)
    created=client.post('/sessions',json={'schema_version':2,'scenario':'w03-contract-fixture'}).json()
    sid=created['session_id'];client.headers['Authorization']='Bearer '+created['token']
    return app,client,sid


def call(api,path,operation,payload,method='POST'):
    app,client,sid=api;auth=app.state.v2_store.authenticate(sid,client.headers['Authorization'].removeprefix('Bearer '));state=app.state.v2_store.view(auth).state
    body={'schema_version':2,'request_id':uuid4().hex,'expected_version':state.business_seq,'expected_workspace_revision':state.workspace_revision,'operation':operation,'payload':payload}
    return client.request(method,f'/sessions/{sid}'+path,json=body)


def test_gateway_crud_batch_adoption_and_no_private_tables(api):
    app,client,sid=api
    task=call(api,'/work-items','work_items.create',{'title':'自主事项'});assert task.status_code==200,task.text
    taskref=task.json()['result']['ref']
    product=call(api,'/work-products','work_products.create',{'kind':'text','task':taskref,'content':'先保留问题','purpose':'exploration'});assert product.status_code==200,product.text
    obj=product.json()['result']['object'];pid=obj['product_id']
    adopted=call(api,f'/work-products/{pid}/adoption','work_products.adopt',{'product_id':pid,'product_version':1,'expected_head':1,'status':'adopted'})
    assert adopted.status_code==200,adopted.text
    assert adopted.json()['result']['object']['adoption']['status']=='adopted'
    listed=client.get(f'/sessions/{sid}/work-products').json()['result']['result']
    assert listed['items'][0]['version']==2
    batch=call(api,'/work-items/batch','work_items.batch',{'creates':[{'title':'子问题','parent':taskref}],'updates':[{'item_id':taskref['object_id'],'expected_revision':1,'status':'paused'}]})
    assert batch.status_code==200,batch.text
    from sqlalchemy import inspect
    assert not any(name.startswith('w03_workspace_') for name in inspect(app.state.v2_store.db.engine).get_table_names())
    assert batch.json()['state']['business_seq']==0


def test_gateway_removed_parent_does_not_prevent_existing_work_edits(api):
    app,client,sid=api
    parent=call(api,'/work-items','work_items.create',{'title':'可整理的事项'}).json()['result']['ref']
    child=call(api,'/work-items','work_items.create',{'title':'保留子事项','parent':parent}).json()['result']['object']
    p=call(api,'/work-products','work_products.create',{'kind':'text','task':parent,'content':'保持原文'}).json()['result']['object']
    removed=call(api,'/work-items/'+parent['object_id'],'work_items.update',{'item_id':parent['object_id'],'expected_revision':1,'status':'removed'},'PATCH');assert removed.status_code==200
    changed=call(api,'/work-items/'+child['id'],'work_items.update',{'item_id':child['id'],'expected_revision':1,'priority':0},'PATCH');assert changed.status_code==200,changed.text
    edit=call(api,f"/work-products/{p['product_id']}/versions",'work_products.versions.create',{'product_id':p['product_id'],'expected_head':1,'kind':'text','task':parent,'content':'继续补证'})
    assert edit.status_code==200,edit.text
    assert edit.json()['result']['object']['version']==2
