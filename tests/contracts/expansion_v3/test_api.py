from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient
import pytest
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry,ScenarioRegistration,Operation
from career_lab.contracts.v2 import *
from career_lab.storage.v2_store import Mutation
from career_lab.storage.v2_lifecycle import record_review,record_submission,begin_revision
from .conftest import product_plan

class Empty(V2):pass

def registry(bindings,config):
    modules=ExtensionRegistry();modules.register_scenario('contract-test',ScenarioRegistration(bindings,config,{'capacity':30,'private_resource':123}))
    modules.register(Operation('work_products.create','act',Empty,product_plan))
    modules.register(Operation('reviews.create','act',ReviewInput,record_review))
    modules.register(Operation('submissions.create','submit',SubmitInput,record_submission))
    modules.register(Operation('revision_cycles','act',BeginRevisionInput,begin_revision,action_name='begin_revision'))
    return modules

def test_http_v2_envelope_identity_replay_and_lifecycle(tmp_path,foundation):
    _,_,_,bindings,config=foundation
    app=create_app('sqlite:///'+str(tmp_path/'api.db'),extensions=registry(bindings,config))
    with TestClient(app) as client:
        created=client.post('/sessions',json={'schema_version':2,'scenario':'contract-test'})
        assert created.status_code==200,created.text
        data=created.json();sid=data['session_id'];headers={'Authorization':'Bearer '+data['token']}
        assert 'private_resource' not in created.text
        def send(endpoint,key,operation,payload,seq=0,wr=0):
            return client.post(f'/sessions/{sid}/{endpoint}',headers=headers,json={'schema_version':2,'request_id':key,'operation':operation,'expected_version':seq,'expected_workspace_revision':wr,'payload':payload})
        response=send('work-products','p','work_products.create',{})
        assert response.status_code==200,response.text
        product=response.json()['objects'][0]
        replay=send('work-products','p','work_products.create',{})
        assert replay.json()['replayed'] and replay.json()['transaction_id']==response.json()['transaction_id']
        spoof=send('work-products','spoof','work_products.create',{'executor':{'kind':'human','id':'forged'}},wr=1)
        assert spoof.status_code==422
        mismatch=send('submissions','bypass','work_products.create',{'decision':'no_go','products':[product]},wr=1)
        assert mismatch.status_code==403
        review=send('reviews','review','reviews.create',{'subjects':[product],'purpose':'exploration','scope':['reasoning']},wr=1)
        assert review.status_code==200 and review.json()['state']['status']=='active'
        submission=send('submissions','sub','submissions.create',{'decision':'no_go','products':[product]},wr=2)
        assert submission.status_code==200,submission.text
        parent=submission.json()['result']['submission']
        revised=send('revision-cycles','revision','begin_revision',{'parent_submission':parent,'reason':'补证'},seq=1,wr=3)
        assert revised.status_code==200 and revised.json()['state']['status']=='active',revised.text
        assert client.get(f'/sessions/{sid}/tools',headers=headers).status_code==503
        assert client.get(f'/sessions/{sid}/work-products').status_code==401
        assert client.get(f'/sessions/{sid}',headers={'Authorization':'Bearer wrong'}).status_code==401
        assert client.post(f'/sessions/{sid}/artifacts',headers=headers,json={'request_id':'old','content':{}}).status_code==409
        assert client.post('/sessions',json={'schema_version':2,'scenario':'not-installed'}).status_code==503
        assert not any('snapshot' in path or 'restore' in path for path in app.openapi()['paths'])

def test_legacy_api_unknown_fields_and_request_bytes_stay_strict(tmp_path):
    with TestClient(create_app('sqlite:///'+str(tmp_path/'v1-api.db'))) as client:
        created=client.post('/sessions',json={}).json();sid=created['session_id'];h={'Authorization':'Bearer '+created['token']}
        body={'tool':'read_material','arguments':{'material_id':'brief'},'request_id':'fixed','expected_version':0}
        first=client.post(f'/sessions/{sid}/actions',headers=h,json=body)
        assert first.status_code==200
        assert client.post(f'/sessions/{sid}/actions',headers=h,json=body).json()['replayed']
        assert client.post(f'/sessions/{sid}/actions',headers=h,json=body|{'executor':'spoof'}).status_code==422
        assert client.post(f'/sessions/{sid}/actions',headers=h,json=body|{'arguments':{'material_id':'faq'}}).status_code==409
        error=client.post(f'/sessions/{sid}/turns',headers=h,json={'role_id':'supervisor','text':'missing request id'})
        assert error.json()['detail'][0]['loc']==['body','request_id']

# Imported protocol models are not pytest test classes.
globals().pop('TestRequestV2', None)
globals().pop('TestResultV2', None)
globals().pop('TestCase', None)
globals().pop('TestPlanPayload', None)
globals().pop('TestCampaign', None)

globals().pop('TestExecutionMetadata', None)


def test_public_write_response_parses_without_internal_state(tmp_path,foundation):
    from career_lab.contracts.v2 import PublicTransactionResult
    _,_,_,bindings,config=foundation
    with TestClient(create_app('sqlite:///'+str(tmp_path/'public.db'),extensions=registry(bindings,config))) as client:
        session=client.post('/sessions',json={'schema_version':2,'scenario':'contract-test'}).json();sid=session['session_id']
        response=client.post(f'/sessions/{sid}/work-products',headers={'Authorization':'Bearer '+session['token']},json={'schema_version':2,'request_id':'p','expected_version':0,'expected_workspace_revision':0,'operation':'work_products.create','payload':{}})
        assert response.status_code==200,response.text
        parsed=PublicTransactionResult.model_validate(response.json())
        assert parsed.boundary.request_id=='p' and parsed.executor.kind=='human'
        assert 'resources' not in parsed.state.model_dump() and 'private_resource' not in response.text
