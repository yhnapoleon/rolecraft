"""W02 supplies persisted facts for W05's rubric; no labels or score policy here."""
import json
from .test_reference_http import live


def dump_handoff(live,path,tests):
    view=live.store.view(live.owner);private=view.private_scenario_state
    facts={'source':'actual_HTTP_Gateway_SQLite','session_id':live.sid,
        'scenario_hash':view.bindings.scenario.sha256,
        'semantic_status':'waiting_for_model','rule_policy_owner':'W05','rubric_installed':False,
        'as_of':view.state.model_dump(mode='json'),
        'policy_activation':{key:value for key,value in private.material_activation.items() if key.startswith('policy:')},
        'source_policy_version':private.source_versions['policy'],
        'indexed_policy_version':private.indexed_versions['policy'],
        'current_config':private.current_config.model_dump(mode='json'),
        'tests':tests,
        'events':[e for step in live.steps for e in step['response'].get('events',[]) if e['type'] in {'initial_plan_applied','index_refreshed','config_applied'}],
        'no_semantic_progress_claim':True}
    path.write_text(json.dumps(facts,ensure_ascii=False,indent=2)+'\n')
    return facts


def test_material_activation_stale_and_fresh_retest_use_actual_fixed_config_and_sources(live,tmp_path):
    first,_=live.post('tests','before','tests.create',{'query':'住宿报销上限是多少？','config_version':0})
    assert first.status_code==200;baseline=first.json()['result']['test']
    config=baseline['config']['requested']|{'version':2,'config_version':1,'freshness_guard':'warn'}
    applied,_=live.post('actions','apply','apply_config',{'tool':'apply_config','config':config});assert applied.status_code==200
    stale,_=live.post('tests','stale','tests.create',{'query':'住宿报销上限是多少？','config_version':1});assert stale.status_code==200
    stale=stale.json()['result']['test']
    refresh,_=live.post('actions','refresh','refresh_index',{'tool':'refresh_index'});assert refresh.status_code==200
    fresh,_=live.post('tests','fresh','tests.create',{'query':'住宿报销上限是多少？','config_version':1});assert fresh.status_code==200
    fresh=fresh.json()['result']['test']
    report=dump_handoff(live,tmp_path/'rubric-facts-retested.json',[baseline,stale,fresh])
    activation=report['policy_activation']['policy:2']
    assert baseline['as_of']['business_seq']<activation<=stale['as_of']['business_seq']
    assert stale['config_ref']==fresh['config_ref']==report['current_config']
    assert baseline['execution']['source_versions']['policy']==1
    assert stale['execution']['source_versions']['policy']==2 and stale['execution']['indexed_versions']['policy']==1
    assert fresh['execution']['source_versions']['policy']==fresh['execution']['indexed_versions']['policy']==2
    assert baseline['citations'][0]['version']==stale['citations'][0]['version']==1
    assert fresh['citations'][0]['version']==2
    assert '500' in baseline['answer'] and '400' in fresh['answer']


def test_update_without_retest_keeps_prechange_result_and_cannot_claim_new_test(live,tmp_path):
    first,_=live.post('tests','before','tests.create',{'query':'住宿报销上限是多少？','config_version':0});assert first.status_code==200
    baseline=first.json()['result']['test'];config=baseline['config']['requested']|{'version':2,'config_version':1}
    applied,_=live.post('actions','apply','apply_config',{'tool':'apply_config','config':config});assert applied.status_code==200
    report=dump_handoff(live,tmp_path/'rubric-facts-not-retested.json',[baseline])
    assert all(t['as_of']['business_seq']<report['policy_activation']['policy:2'] for t in report['tests'])
    assert report['current_config']!=baseline['config_ref']
    recovered=live.http('GET',f'/sessions/{live.sid}/requests/before',headers=live.headers)
    assert recovered.status_code==200 and recovered.json()['response']==first.json()
