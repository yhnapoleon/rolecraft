"""W03 owned handlers through fixed c7 Gateway/V2Store, never a bypass router."""
from datetime import datetime,timedelta,timezone
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from career_lab.contracts import v2 as C
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry,ScenarioRegistration
from career_lab.storage.v2_tables import v2_objects,v2_transactions,v2_events
from career_lab.workspace.extension import install_workspace_operations,workspace_plan,snapshot_from_view
from career_lab.workspace.imports import MAX_SOURCE_REVISION,MAX_VERSION_SPAN,MAX_HISTORY_PER_ITEM,MAX_REFERENCES
from test_formal_gateway import api,call,product_page


def counts(store):
    with store.db.engine.connect() as conn:return tuple(conn.execute(select(func.count()).select_from(t)).scalar_one() for t in (v2_objects,v2_transactions,v2_events))


def create_shared(api,title,role):
    app,client,sid=api
    product=call(api,'/work-products','work_products.create',{'kind':'text','title':title,'content':title}).json()['result']['object'];pid=product['product_id']
    response=call(api,f'/work-products/{pid}/shares','work_products.shares.create',{'product_id':pid,'product_version':1,'recipient_role':role})
    assert response.status_code==200,response.text
    return product,C.ObjectRef.model_validate(response.json()['result']['ref'])


def command(store,auth,payload,key):
    state=store.view(auth).state
    return C.Command(schema_version=2,request_id=key,operation='work_products.versions.create',expected_version=state.business_seq,expected_workspace_revision=state.workspace_revision,payload=payload)


def test_actual_scoped_handler_removes_only_target_without_revealing_hidden_shares(api):
    app,client,sid=api;store=app.state.v2_store;owner=store.authenticate(sid,client.headers['Authorization'].split()[1])
    a,sa=create_shared(api,'target','tech_lead');b,sb=create_shared(api,'OTHER-PRODUCT-PRIVATE','business_lead')
    grant=C.DelegationGrant(id='one-product',session_id=sid,actor_id='learner',executor=C.Executor(id='agent',kind='external_agent',delegation_id='one-product'),capabilities=('read','act'),allowed_objects=(a['product_id'],),allowed_actions=('work_products.list','work_products.shares.list','work_products.versions.create'),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    token=store.issue_delegation(owner,grant);agent=store.authenticate(sid,token);limited=TestClient(app);limited.headers['Authorization']='Bearer '+token
    page=product_page(limited,sid);assert len(page['items'])==1 and not page['sharing_complete'] and page['items'][0]['visibility'] is None
    listing=limited.get(f"/sessions/{sid}/work-products/{a['product_id']}/shares");assert listing.status_code==200
    assert listing.json()['result']['result']['items']==[] and not listing.json()['result']['result']['sharing_complete']
    payload={'product_id':a['product_id'],'expected_head':1,'kind':'text','content':a['content'],'title':a['title'],'removed':True}
    body=command(store,agent,payload,'scoped-remove').model_dump(mode='json')
    result=limited.post(f"/sessions/{sid}/work-products/{a['product_id']}/versions",json=body);assert result.status_code==200,result.text
    assert sa.object_id not in result.text and sb.object_id not in result.text and 'OTHER-PRODUCT-PRIVATE' not in result.text
    assert result.json()['result']['removals'][0]['visible_revocations']==[]
    with pytest.raises(C.ProtocolError):store.read_shared_product(store.role_reader(sid,'tech_lead'),sa)
    assert store.read_shared_product(store.role_reader(sid,'business_lead'),sb).ref.object_id==b['product_id']
    after=counts(store)
    denied=call((app,limited,sid),f"/work-products/{b['product_id']}/versions",'work_products.versions.create',{'product_id':b['product_id'],'expected_head':1,'kind':'text','content':'intrude','removed':True})
    assert denied.status_code in {403,404} and counts(store)==after and 'OTHER-PRODUCT-PRIVATE' not in denied.text
    restored=call((app,limited,sid),f"/work-products/{a['product_id']}/versions",'work_products.versions.create',{**payload,'expected_head':2,'removed':False});assert restored.status_code==200,restored.text
    with pytest.raises(C.ProtocolError):store.read_shared_product(store.role_reader(sid,'tech_lead'),sa)
    assert not store.view(agent).objects or all(x.ref.kind!='share' for x in store.view(agent).objects)
    # Keep this last so isolation/restore are exercised even when c7 replay's
    # structural-cycle scope bug is still present. Do not xfail the real failure.
    after=counts(store);again=limited.post(f"/sessions/{sid}/work-products/{a['product_id']}/versions",json=body)
    assert again.status_code==200 and again.json()['replayed'] and counts(store)==after,again.text


def test_owned_removal_rolls_back_cascade_and_same_key_can_retry(api):
    app,client,sid=api;store=app.state.v2_store;owner=store.authenticate(sid,client.headers['Authorization'].split()[1]);p,sref=create_shared(api,'retained','tech_lead')
    grant=C.DelegationGrant(id='rollback-agent',session_id=sid,actor_id='learner',executor=C.Executor(id='agent',kind='external_agent',delegation_id='rollback-agent'),capabilities=('read','act'),allowed_objects=(p['product_id'],),expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    auth=store.authenticate(sid,store.issue_delegation(owner,grant));payload={'product_id':p['product_id'],'expected_head':1,'kind':'text','content':p['content'],'removed':True}
    cmd=command(store,auth,payload,'rollback-owned');old=store.view(owner).state;before=counts(store)
    handler=lambda v,c,a:workspace_plan(v,c,a,roles=('tech_lead',),resolvers={})
    with pytest.raises(C.ProtocolError,match='share scope incomplete'):handler(store.view(auth),cmd,auth)
    def fault(stage):
        if stage=='after_objects':raise RuntimeError('owned rollback')
    with pytest.raises(RuntimeError,match='owned rollback'):store.execute(auth,cmd,handler,fault=fault)
    assert counts(store)==before and store.view(owner).state==old
    assert store.read_shared_product(store.role_reader(sid,'tech_lead'),sref).ref.version==1
    result=store.execute(auth,cmd,handler);assert result.result['removals'][0]['all_active_shares_revoked']
    assert store.execute(auth,cmd,handler).replayed
    with pytest.raises(C.ProtocolError):store.read_shared_product(store.role_reader(sid,'tech_lead'),sref)


def import_body(sid,raws,refs=(),package_id='import-c7'):
    items=tuple(C.LegacyProvenance(source_schema='browser-v1',source_session_id=sid,original_id=r['id'],original_kind=r['kind'],raw=r,original_hash=C.digest(r)) for r in raws)
    return C.WorkspaceImport(package_id=package_id,mode='preview',source_schema='browser-v1',source_session_id=sid,items=items,references=refs,package_hash=C.digest([i.model_dump(mode='json') for i in items])).model_dump(mode='json')


@pytest.mark.parametrize('raws',[
    [{'id':'huge-label','kind':'text','body':'x','revision':MAX_SOURCE_REVISION+1}],
    [{'id':f'g{i}','kind':'text','body':'x','revision':MAX_SOURCE_REVISION} for i in range(MAX_VERSION_SPAN//MAX_SOURCE_REVISION+1)],
    [{'id':'many-history','kind':'text','body':'x','revision':2,'sourceHistory':[{'revision':1,'kind':'text','body':'old'}]*(MAX_HISTORY_PER_ITEM+1)}],
])
def test_small_import_cannot_expand_unbounded_revision_rows_or_write_partial(api,raws):
    app,client,sid=api;store=app.state.v2_store;auth=store.authenticate(sid,client.headers['Authorization'].split()[1]);body=import_body(sid,raws);before=counts(store);state=store.view(auth).state
    result=call(api,'/workspace-imports','workspace_imports',body)
    assert result.status_code==422 and result.json()['code']=='import_history_limit',result.text
    assert len(result.content)<1000 and counts(store)==before and store.view(auth).state==state
    result=call(api,'/workspace-imports','workspace_imports',{**body,'mode':'apply','preview_storage_revision':state.storage_revision})
    assert result.status_code==422 and counts(store)==before


def test_import_explicit_resolution_survives_inference_and_receipt_recovery(api):
    app,client,sid=api;store=app.state.v2_store;auth=store.authenticate(sid,client.headers['Authorization'].split()[1])
    target=next(r.ref for r in store.view(auth).objects if r.ref.kind=='config')
    refs=(C.ImportReference(original_id=target.object_id,original_session_id=sid,status='resolved',resolved=target),)
    raw={'id':'source-work','kind':'text','body':'current','revision':3,'evidence':[{'id':target.object_id}],'sourceHistory':[{'revision':1,'kind':'text','body':'old'}]}
    body=import_body(sid,[raw],refs);before=counts(store);state=store.view(auth).state
    preview=call(api,'/workspace-imports','workspace_imports',body);assert preview.status_code==200,preview.text
    result=preview.json()['result'];assert result['unresolved']==[] and len(result['conflicts'])==1 and result['conflicts'][0]['reason']=='missing_history'
    assert counts(store)==before and store.view(auth).state==state
    payload={**body,'mode':'apply','preview_storage_revision':result['as_of']['storage_revision']}
    c={'schema_version':2,'request_id':'actual-import','operation':'workspace_imports','expected_version':state.business_seq,'expected_workspace_revision':state.workspace_revision,'payload':payload}
    applied=client.post(f'/sessions/{sid}/workspace-imports',json=c);assert applied.status_code==200,applied.text
    after=counts(store);replayed=client.post(f'/sessions/{sid}/workspace-imports',json=c)
    assert replayed.json()['replayed'] and counts(store)==after
    recovered=client.get(f'/sessions/{sid}/requests/actual-import');assert recovered.status_code==200
    assert recovered.json()['response']['result']==applied.json()['result']
    receipts=client.get(f'/sessions/{sid}/workspace-imports').json()['result']['result']['items']
    assert len(receipts)==1 and receipts[0]['result']['unresolved']==[]
    assert [r.content['content'] for r in store.view(auth).objects if r.ref.kind=='product']==['old','current']


def test_duplicate_explicit_reference_conflict_is_rejected_without_guessing(api):
    app,client,sid=api;store=app.state.v2_store;auth=store.authenticate(sid,client.headers['Authorization'].split()[1]);target=next(r.ref for r in store.view(auth).objects if r.ref.kind=='config')
    good=C.ImportReference(original_id=target.object_id,original_session_id=sid,status='resolved',resolved=target)
    bad=C.ImportReference(original_id=target.object_id,original_session_id=sid,status='unverified_local')
    body=import_body(sid,[{'id':'p','kind':'text','body':'text'}],(good,bad));before=counts(store)
    reply=call(api,'/workspace-imports','workspace_imports',body);assert reply.status_code==422 and reply.json()['code']=='conflicting_import_reference'
    assert counts(store)==before


def test_contextual_reference_uses_transaction_authority_and_cannot_escape(tmp_path):
    text='Public source text';path=tmp_path/'material.txt';path.write_text(text);import hashlib
    f=C.FileRef(path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest());registry=ExtensionRegistry();calls=[]
    def resolve(auth,ref,as_of,bindings,*,scenario_state):
        assert scenario_state is not None;calls.append(scenario_state.version)
        if scenario_state.material_activation.get('material:'+str(ref.version)) is None:raise C.ProtocolError('material_unavailable',status=404)
        C.read_file(tmp_path,f)
        return C.ExternalReference(ref=C.ObjectRef.model_validate({k:v for k,v in ref.model_dump(mode='json').items() if k in C.ObjectRef.model_fields}),source=f,content_hash=f.sha256)
    registry.register_reference_resolver('material',resolve,contextual=True)
    config=C.AssistantConfig(id='config',session_id='fixture',domains=('faq',));private=C.ScenarioStateV2(id='scenario',session_id='fixture',version=1,current_config=C.ObjectRef(session_id='fixture',kind='config',object_id='config',version=1,config_version=0),source_versions={'material':1},indexed_versions={'material':1},material_activation={'material:1':0})
    registry.register_scenario('context-fixture',ScenarioRegistration(C.SessionBindings(scenario=f,runtime=f,evaluation=f),config,{},private));install_workspace_operations(registry,roles=('tech_lead',))
    app=create_app(f'sqlite:///{tmp_path / "context.db"}',extensions=registry);client=TestClient(app);created=client.post('/sessions',json={'schema_version':2,'scenario':'context-fixture'}).json();sid=created['session_id'];client.headers['Authorization']='Bearer '+created['token'];api=(app,client,sid)
    evidence=C.EvidenceRefV2(session_id=sid,kind='material',object_id='material',version=1,observed_at_seq=0,quote='Public',span_start=0,span_end=6)
    response=call(api,'/work-products','work_products.create',{'kind':'text','content':'quoted','evidence_refs':[evidence.model_dump(mode='json')]});assert response.status_code==200,response.text
    assert calls and all(v==1 for v in calls)
    auth=app.state.v2_store.authenticate(sid,created['token']);saved=app.state.v2_store.query(auth,lambda v:snapshot_from_view(v,auth,(),{}))
    with pytest.raises(C.ProtocolError,match='reference view expired'):saved.reference_allowed(evidence)
    ordinary=snapshot_from_view(app.state.v2_store.view(auth),auth,(),{'material':lambda *_:pytest.fail('standalone resolver must not run')})
    with pytest.raises(C.ProtocolError,match='reference view required'):ordinary.reference_allowed(evidence)


def test_total_expansion_and_inferred_reference_limits_are_checked_before_writes(api,monkeypatch):
    import career_lab.workspace.imports as imports
    app,client,sid=api;store=app.state.v2_store;before=counts(store)
    monkeypatch.setattr(imports,'MAX_EXPANDED_BYTES',1000)
    body=import_body(sid,[{'id':'bounded','kind':'text','body':'small'}])
    response=call(api,'/workspace-imports','workspace_imports',body)
    assert response.status_code==422 and response.json()['code']=='import_expansion_limit' and counts(store)==before
    monkeypatch.setattr(imports,'MAX_EXPANDED_BYTES',8_000_000);monkeypatch.setattr(imports,'MAX_REFERENCES',2)
    body=import_body(sid,[{'id':'refs','kind':'text','body':'small','evidence':[{'id':'a'},{'id':'b'},{'id':'c'}]}])
    response=call(api,'/workspace-imports','workspace_imports',body)
    assert response.status_code==422 and response.json()['code']=='import_reference_limit' and counts(store)==before


def test_explicit_existing_task_resolution_does_not_become_missing_task(api):
    app,client,sid=api
    task=call(api,'/work-items','work_items.create',{'title':'Existing task'}).json()['result']['ref']
    resolution=C.ImportReference(original_id=task['object_id'],original_session_id=sid,status='resolved',resolved=C.ObjectRef.model_validate(task))
    body=import_body(sid,[{'id':'new-linked-work','kind':'text','body':'kept','taskId':task['object_id']}],(resolution,))
    preview=call(api,'/workspace-imports','workspace_imports',body);assert preview.status_code==200,preview.text
    assert preview.json()['result']['unresolved']==[]
    applied=call(api,'/workspace-imports','workspace_imports',{**body,'mode':'apply','preview_storage_revision':preview.json()['result']['as_of']['storage_revision']})
    assert applied.status_code==200,applied.text
    assert product_page(client,sid)['items'][0]['task']==task
