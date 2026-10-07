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


def product_page(client,sid):
    response=client.get(f'/sessions/{sid}/work-products')
    assert response.status_code==200,response.text
    return response.json()['result']['result']


def test_gateway_sharing_projection_survives_new_client_and_revocation(api):
    from career_lab.contracts.v2 import ObjectRef,ProtocolError,DelegationGrant,Executor
    app,client,sid=api;store=app.state.v2_store
    owner=store.authenticate(sid,client.headers['Authorization'].removeprefix('Bearer '))
    original=call(api,'/work-products','work_products.create',{'kind':'text','content':'原始准确版本'}).json()['result']
    pid=original['object']['product_id'];pref=ObjectRef.model_validate(original['ref'])
    saved_before=store.read(owner,pref).model_dump_json()
    share=call(api,f'/work-products/{pid}/shares','work_products.shares.create',{'product_id':pid,'product_version':1,'recipient_role':'tech_lead'}).json()['result']['object']
    role=store.role_reader(sid,'tech_lead');sref=ObjectRef(session_id=sid,kind='share',object_id=share['id'],version=1)
    assert store.read_shared_product(role,sref).ref==pref
    # A fresh HTTP client has no previous mutation response or local cache.
    fresh=TestClient(app);fresh.headers['Authorization']=client.headers['Authorization']
    page=product_page(fresh,sid)
    assert page['sharing_complete'] is True and page['items'][0]['visibility']=='shared'
    assert page['items'][0]['shares'][0]['object_id']==share['id']
    assert page['shares'][0]['product']['version']==1 and page['shares'][0]['recipient_role']=='tech_lead'
    assert page['shares'][0]['version']==1 and page['shares'][0]['revoked_at'] is None
    grant=DelegationGrant(id='read-all',session_id=sid,actor_id='learner',executor=Executor(id='agent',kind='external_agent',delegation_id='read-all'),capabilities=('read',),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    agent=TestClient(app);agent.headers['Authorization']='Bearer '+store.issue_delegation(owner,grant)
    assert product_page(agent,sid)==page
    recovered=page['shares'][0]
    revoked=call(api,f"/work-products/{pid}/shares/{recovered['id']}",'work_products.shares.change',{'product_id':pid,'share_id':recovered['id'],'expected_revision':recovered['version'],'operation':'revoke'})
    assert revoked.status_code==200,revoked.text
    after=product_page(fresh,sid)
    assert after['items'][0]['visibility']=='private' and after['shares'][0]['version']==2
    assert after['shares'][0]['revoked_at'] is not None
    with pytest.raises(ProtocolError):store.read_shared_product(role,sref)
    assert store.read(owner,pref).model_dump_json()==saved_before
    assert store.read(owner,sref).content['revoked_at'] is None


def test_gateway_old_version_share_does_not_mark_unshared_new_version_shared(api):
    app,client,sid=api
    original=call(api,'/work-products','work_products.create',{'kind':'text','content':'v1'}).json()['result']['object'];pid=original['product_id']
    shared=call(api,f'/work-products/{pid}/shares','work_products.shares.create',{'product_id':pid,'product_version':1,'recipient_role':'tech_lead'});assert shared.status_code==200
    edited=call(api,f'/work-products/{pid}/versions','work_products.versions.create',{'product_id':pid,'expected_head':1,'kind':'text','content':'v2'});assert edited.status_code==200
    page=product_page(client,sid)
    assert page['items'][0]['version']==2 and page['items'][0]['visibility']=='private' and page['items'][0]['shares']==[]
    assert page['shares'][0]['product']['version']==1 and page['shares'][0]['revoked_at'] is None
    versions=client.get(f'/sessions/{sid}/work-products/{pid}/versions').json()['result']['result']['items']
    assert [(v['version'],v['visibility']) for v in versions]==[(1,'shared'),(2,'private')]


def test_gateway_remove_revokes_all_shares_atomically_restore_needs_explicit_reshare(api):
    from career_lab.contracts.v2 import ObjectRef,ProtocolError
    app,client,sid=api;store=app.state.v2_store
    owner=store.authenticate(sid,client.headers['Authorization'].removeprefix('Bearer '))
    original=call(api,'/work-products','work_products.create',{'kind':'text','content':'保留已被引用的原文'}).json()['result'];pid=original['object']['product_id']
    p1=ObjectRef.model_validate(original['ref']);old_bytes=store.read(owner,p1).model_dump_json()
    refs=[];roles=[]
    for role_id in ('tech_lead','business_lead'):
        response=call(api,f'/work-products/{pid}/shares','work_products.shares.create',{'product_id':pid,'product_version':1,'recipient_role':role_id})
        assert response.status_code==200;refs.append(ObjectRef.model_validate(response.json()['result']['ref']));roles.append(store.role_reader(sid,role_id))
    before=store.view(owner).state
    removed=call(api,f'/work-products/{pid}/versions','work_products.versions.create',{'product_id':pid,'expected_head':1,'kind':'text','content':'保留已被引用的原文','removed':True})
    assert removed.status_code==200,removed.text
    view=store.view(owner);assert view.state.workspace_revision==before.workspace_revision+1 and view.state.storage_revision==before.storage_revision+1
    assert view.state.business_seq==before.business_seq
    for role,sref in zip(roles,refs):
        with pytest.raises(ProtocolError):store.read_shared_product(role,sref)
        assert store.read(owner,sref).content['revoked_at'] is None
    page=product_page(client,sid);assert all(s['revoked_at'] is not None and s['version']==2 for s in page['shares'])
    assert all(s['revoked_at']['storage_revision']==view.state.storage_revision for s in page['shares'])
    restored=call(api,f'/work-products/{pid}/versions','work_products.versions.create',{'product_id':pid,'expected_head':2,'kind':'text','content':'保留已被引用的原文','removed':False});assert restored.status_code==200,restored.text
    assert product_page(client,sid)['items'][0]['visibility']=='private'
    for role,sref in zip(roles,refs):
        with pytest.raises(ProtocolError):store.read_shared_product(role,sref)
    again=call(api,f'/work-products/{pid}/shares','work_products.shares.create',{'product_id':pid,'product_version':3,'recipient_role':'tech_lead'})
    assert again.status_code==200,again.text
    assert store.read_shared_product(roles[0],ObjectRef.model_validate(again.json()['result']['ref'])).ref.version==3
    assert store.read(owner,p1).model_dump_json()==old_bytes
    assert len(client.get(f'/sessions/{sid}/work-products/{pid}/versions').json()['result']['result']['items'])==3


def test_scoped_product_agent_cannot_treat_filtered_shares_as_empty_or_partially_remove(api):
    from career_lab.contracts.v2 import ObjectRef,DelegationGrant,Executor
    app,client,sid=api;store=app.state.v2_store
    owner=store.authenticate(sid,client.headers['Authorization'].removeprefix('Bearer '))
    original=call(api,'/work-products','work_products.create',{'kind':'text','content':'private'}).json()['result']['object'];pid=original['product_id']
    shared=call(api,f'/work-products/{pid}/shares','work_products.shares.create',{'product_id':pid,'product_version':1,'recipient_role':'tech_lead'}).json()['result']
    grant=DelegationGrant(id='product-only',session_id=sid,actor_id='learner',executor=Executor(id='limited',kind='external_agent',delegation_id='product-only'),capabilities=('read','act'),allowed_objects=(pid,),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    restricted=TestClient(app);restricted.headers['Authorization']='Bearer '+store.issue_delegation(owner,grant)
    page=product_page(restricted,sid);assert page['sharing_complete'] is False
    assert 'visibility' not in page['items'][0] and page['shares']==[]
    before=store.view(owner).state
    denied=call((app,restricted,sid),f'/work-products/{pid}/versions','work_products.versions.create',{'product_id':pid,'expected_head':1,'kind':'text','content':'private','removed':True})
    assert denied.status_code==403,denied.text
    assert store.view(owner).state==before and product_page(client,sid)['items'][0]['removed_at'] is None
    role=store.role_reader(sid,'tech_lead');assert store.read_shared_product(role,ObjectRef.model_validate(shared['ref'])).content['content']=='private'
