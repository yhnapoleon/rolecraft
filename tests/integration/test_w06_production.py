"""Actual W02/W03/Gateway data; c9's missing history port is explicit.

The test bridge captures real committed public HTTP results, not authored source
fragments. It is not the production shared-store history implementation.
"""
from dataclasses import replace
from pathlib import Path
import json
import importlib.util
from uuid import uuid4
from datetime import datetime,timedelta,timezone

import pytest
from fastapi.testclient import TestClient
from career_lab.contracts import v2 as C
from career_lab.delegations.factory import create_scenario_app
from career_lab.delegations.sources import MaterialReadReceipt,PublicHistoryWindow,point
from career_lab.scenarios.v2.seed import build_seed


class CapturedPublicHistory:
    def __init__(self):self.responses=[]
    def __call__(self,view,page,auth):
        events=[];reads=[]
        for response in self.responses:
            if response.state.session_id!=auth.session_id:continue
            for event in response.events:
                if event.seq>view.state.business_seq:continue
                if event.type=='material_read':
                    ref=C.ObjectRef(session_id=auth.session_id,kind='material',object_id=event.data['material_id'],version=event.data['version'])
                    try:allowed=view.reference_allowed(ref)
                    except C.ProtocolError:allowed=False
                    if not allowed:continue
                    reads.append(MaterialReadReceipt(event,tuple(C.DisclosedFragment.model_validate(f) for f in response.result['fragments'])))
                if all(view.reference_allowed(ref) for ref in event.refs):events.append(event)
        # Test traffic contains no untracked commands. Public events are real
        # Gateway outputs; this bridge substitutes only the missing query port.
        end=min(view.state.business_seq,(page.since_seq or 0)+page.limit)
        return PublicHistoryWindow(point(view.state),tuple(e for e in events if (page.since_seq or 0)<e.seq<=end),tuple(reads),end,True)


@pytest.fixture
def production(tmp_path):
    # Real W02 authored package builder; no hand-written MATERIAL/test fixture.
    # Temporary package is for adapter execution, not the new approved release.
    package=build_seed(tmp_path/'authored-package')
    history=CapturedPublicHistory()
    app=create_scenario_app(database_url='sqlite:///'+str(tmp_path/'production.db'),scenario_package=package,history_reader=history)
    client=TestClient(app);created=client.post('/sessions',json={'schema_version':2,'scenario':'pm_pilot_v2'}).json()
    sid=created['session_id'];client.headers['Authorization']='Bearer '+created['token']
    owner=app.state.v2_store.authenticate(sid,created['token'])
    def command(operation,payload,request_id=None):
        state=app.state.v2_store.view(owner).state
        return C.Command(schema_version=2,request_id=request_id or uuid4().hex,expected_version=state.business_seq,expected_workspace_revision=state.workspace_revision,operation=operation,payload=payload).model_dump(mode='json')
    def send(path,operation,payload,headers=None):
        response=client.post('/sessions/'+sid+'/'+path,json=command(operation,payload),headers=headers)
        assert response.status_code==200,response.text
        result=C.PublicTransactionResult.model_validate(response.json());history.responses.append(result)
        return response.json()
    yield dict(app=app,client=client,sid=sid,owner=owner,token=created['token'],command=command,send=send,history=history,package=package,tmp=tmp_path)
    client.close();app.state.store.close()


def delegate(env,**scope):
    body=C.DelegationInput(agent_label='真实工作区 Codex',expires_at=datetime.now(timezone.utc)+timedelta(minutes=20),capabilities=scope.pop('capabilities',('read','act')),**scope)
    response=env['client'].post('/sessions/'+env['sid']+'/delegations',json=env['command']('delegations.create',body.model_dump(mode='json')))
    assert response.status_code==200,response.text
    return response.json()['result']['result']


def test_w06_actual_scenario_catalog_reads_products_and_test_results(production):
    e=production;c=e['client'];url='/sessions/'+e['sid']
    before=c.get(url+'/observation');assert before.status_code==200,before.text
    observation=C.Observation.model_validate(before.json()['result'])
    assert observation.catalog and observation.visible_sources==() and observation.read_versions==()
    assert not any('private' in m.id for m in observation.catalog)
    item=next(m for m in observation.catalog if m.id=='brief')
    ref=C.ObjectRef(session_id=e['sid'],kind='material',object_id=item.id,version=item.version)
    actual=e['send']('actions','read_material',{'tool':'read_material','material':ref.model_dump(mode='json')})
    created=delegate(e);headers={'Authorization':'Bearer '+created['token']}
    read=c.get(url+'/observation',headers=headers);assert read.status_code==200,read.text
    observed=C.Observation.model_validate(read.json()['result'])
    assert [f.text for f in observed.visible_sources]==[f['text'] for f in actual['result']['fragments']]
    assert all(not f.fact_ids and f.acquired_at_seq==actual['events'][0]['seq'] for f in observed.visible_sources)
    assert observed.read_versions==(ref,) and observed.actor.kind=='external_agent'
    product=e['send']('work-products','work_products.create',{'kind':'investigation','content':observed.visible_sources[0].text},headers=headers)
    result=e['send']('tests','tests.create',{'query':'账号密码忘了怎么重置？','config_version':0},headers=headers)
    assert result['result']['test']['execution']['executor']['kind']=='external_agent'
    assert result['result']['test']['answer']!='Controlled local lookup: no matching source.'
    after=C.Observation.model_validate(c.get(url+'/observation',headers=headers).json()['result'])
    assert after.products and after.tests
    recovered=c.get(url+'/requests/'+product['boundary']['request_id'],headers=headers).json()
    assert recovered['status']=='completed' and recovered['executor']['kind']=='external_agent'
    tools={tool.name for tool in after.tools}
    assert not {'turns.create','feedback.create','research'} & tools


def test_w06_production_read_scope_and_missing_history_are_explicit(production):
    e=production;ref=C.ObjectRef(session_id=e['sid'],kind='material',object_id='brief',version=1)
    e['send']('actions','read_material',{'tool':'read_material','material':ref.model_dump(mode='json')})
    limited=delegate(e,allowed_objects=('faq',))
    response=e['client'].get('/sessions/'+e['sid']+'/observation',headers={'Authorization':'Bearer '+limited['token']})
    assert response.status_code==200,response.text
    observation=C.Observation.model_validate(response.json()['result'])
    assert {m.id for m in observation.catalog}=={'faq'} and observation.visible_sources==()
    app=create_scenario_app(database_url='sqlite:///'+str(e['tmp']/'missing-history.db'),scenario_package=e['package'])
    with TestClient(app) as c:
        created=c.post('/sessions',json={'schema_version':2,'scenario':'pm_pilot_v2'}).json()
        unavailable=c.get('/sessions/'+created['session_id']+'/observation',headers={'Authorization':'Bearer '+created['token']})
        assert unavailable.status_code==503 and unavailable.json()['code']=='observation_history_unavailable'
        tools=c.get('/sessions/'+created['session_id']+'/tools',headers={'Authorization':'Bearer '+created['token']}).json()['result']['result']['tools']
        observation=next(tool for tool in tools if tool['name']=='observation')
        assert not observation['available'] and observation['unavailable_code']=='observation_history_unavailable'
    app.state.store.close()


def test_w06_scenario_factory_preserves_original_binding_validation(tmp_path,stale_contract_scenario):
    with pytest.raises(C.ProtocolError,match='runtime contract mismatch'):
        create_scenario_app(database_url='sqlite:///'+str(tmp_path/'must-not-exist.db'),scenario_package=stale_contract_scenario)
    assert not (tmp_path/'must-not-exist.db').exists()


def displayed_role_history(env):
    source=importlib.util.spec_from_file_location('w06_role_history',Path(__file__).parents[2]/'tests/e2e/test_w06_stdio.py')
    module=importlib.util.module_from_spec(source);source.loader.exec_module(module)
    safe,old=module.seed_role_history(env)
    from career_lab.runtime.roles_v2 import record_reply_display
    store=env['app'].state.v2_store
    command=C.Command.model_validate(env['command']('role_reply.display',{'ref':safe.model_dump(mode='json')}))
    displayed=store.execute(env['owner'],command,record_reply_display)
    return safe,old,displayed.objects[0],module.fixture.PRIVATE


@pytest.mark.parametrize('mode',['owner','read','restricted_act'])
def test_w06_production_display_reads_safe_reply_and_omits_legacy_private_history(production,mode):
    e=production;safe,old,display,secret=displayed_role_history(e)
    headers=None
    if mode!='owner':
        scope={'allowed_objects':('safe-turn',safe.object_id,display.object_id)} if mode=='restricted_act' else {'capabilities':('read',)}
        issued=delegate(e,**scope);headers={'Authorization':'Bearer '+issued['token']}
    outputs=[]
    for suffix in ('/observation?since_seq=0&limit=1','/observation?since_seq=1&limit=1','/tools'):
        response=e['client'].get('/sessions/'+e['sid']+suffix,headers=headers)
        assert response.status_code==200,response.text
        outputs.append(response.text)
        if suffix.startswith('/observation'):
            assert 'Public words only.' in response.text
            observation=C.Observation.model_validate(response.json()['result'])
            assert any(f.acquired_via=='displayed' and f.text=='Public words only.' for f in observation.visible_sources)
    for private in (secret,'prompt_messages','HIDDEN_SOURCE','context_hash','legacy-reply'):
        assert private not in ''.join(outputs)
    store=e['app'].state.v2_store
    assert secret in store.read(store.role_reader(e['sid'],'tech_lead'),old).model_dump_json()
    assert secret in store.read(store.research_context(e['sid']),old).model_dump_json()
