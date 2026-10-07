"""New constraints change actual behavior; these are same-family practice, not research test."""
from dataclasses import asdict
import json, os, socket, subprocess, time
from pathlib import Path
import httpx
import pytest
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.engine import ScenarioEngine
from career_lab.scenarios.v2.seed import build_seed
from career_lab.scenarios.v2.__main__ import paths_report
from career_lab.scenarios.v2.policy import effective_config
from career_lab.storage.v2_store import V2Store
from .test_reference_http import LiveScenario
from .conftest import auth

ROOT=Path(__file__).resolve().parents[3]
PACK=ROOT/'scenarios/pm_pilot/v2'
IDS=('pm_pilot_urgent','pm_pilot_capacity15')

@pytest.fixture(params=[(sid,locale) for sid in IDS for locale in ('zh','en')])
def practice(request):
    sid,locale=request.param
    module=ScenarioModule(PACK/'variants'/sid,work_language=locale)
    return sid,locale,module


def test_constraint_facts_language_lineage_initial_snapshot_and_record_inputs(practice):
    sid,locale,module=practice;p=module.package
    pair=ScenarioModule(PACK/'variants'/sid,work_language='en' if locale=='zh' else 'zh').package
    base=ScenarioModule(PACK,work_language=locale).package
    limits={'capacity':15 if sid.endswith('capacity15') else 30,'dev_days':3,'deadline_day':5 if sid.endswith('urgent') else 7}
    assert dict(p.bundle.initial_resources)==limits
    assert p.locale_metadata['canonical_fact_root_id']==pair.locale_metadata['canonical_fact_root_id']
    assert p.locale_metadata['canonical_fact_root_id']!=base.locale_metadata['canonical_fact_root_id']
    assert p.locale_metadata['lineage']['component_id']==base.locale_metadata['lineage']['component_id']
    assert p.bundle.structure_id==base.bundle.structure_id and p.bundle.split==pair.bundle.split=='train'
    for key,value in limits.items():
        fact=next(f for f in p.facts if f.id==key and f.version==1)
        assert fact.value==value and str(value) in fact.source.quote
    records=json.loads((p.root/'research/public-case-records.json').read_text())['records']
    assert len(records)==12
    for record in records:
        snap=record['input_snapshot']
        assert snap['world']['resources']==limits and snap['world']['business_seq']==0
        assert 'policy:2' not in snap['material_activation']
        assert snap['source_versions']['policy']==snap['indexed_versions']['policy']==1
    state=ScenarioEngine(p).initial('variant-initial')
    result=effective_config(p,state.config,state.world.resources)
    missing='participants' if sid.endswith('capacity15') else 'launch_day'
    assert missing in result.differences
    assert not effective_config(base,base.baseline('base'),base.bundle.initial_resources).differences
    assert not {'probes.json','decision_examples.json','facts.json'} & set(p.bundle.public_files)
    assert all('policy-v2' not in x and 'private' not in x for x in p.bundle.public_files)


def test_variant_keeps_multiple_viable_choices_and_optional_approval(practice):
    sid,locale,module=practice
    report=paths_report(module.package)
    assert len(report['paths'])==5
    for path in report['paths']:
        assert not path['after']['config']['differences'],(path['path'],path['after']['config'])
        if path['decision']:assert path['decision']['status']=='approved',path['decision']
    assert report['paths'][0]['decision'] is None


def test_frozen_variant_can_be_rebuilt_from_its_actual_records(practice,tmp_path):
    sid,locale,module=practice;p=module.package
    records=json.loads((p.root/'research/public-case-records.json').read_text())
    calibration=json.loads((p.root/'research/retrieval-calibration.json').read_text()) if locale=='en' else None
    diagnostic=json.loads((p.root/'research/private-diagnostic.json').read_text()) if (p.root/'research/private-diagnostic.json').exists() else None
    replica=build_seed(tmp_path/'replica',records,locale=locale,scenario_id=sid,english_min_score=.3,calibration=calibration,private_diagnostic=diagnostic)
    assert (replica/'manifest.json').read_bytes()==(p.root/'manifest.json').read_bytes()


@pytest.fixture
def variant_http(practice,tmp_path):
    sid,locale,module=practice;database='sqlite:///'+str(tmp_path/'practice.db')
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    log=(tmp_path/'server.log').open('w')
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'};env['PYTHONDONTWRITEBYTECODE']='1'
    process=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','career_lab.scenarios.v2','serve',str(module.package.root),'--database-url',database,'--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    live=store=None
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=10) as client:
            for _ in range(150):
                if process.poll() is not None:raise RuntimeError('variant server exited')
                try:
                    if client.get('/health').status_code==200:break
                except httpx.TransportError:pass
                time.sleep(.05)
            else:raise RuntimeError('variant server timeout')
            store=V2Store(database);live=LiveScenario(client,store)
            yield sid,locale,module,live
    finally:
        if live is not None:
            (tmp_path/'practice-http.json').write_text(json.dumps({'scenario_id':sid,'locale':locale,'scenario_hash':module.package.content_hash,'public_entry_routing_verified':False,'steps':live.steps},ensure_ascii=False,indent=2)+'\n')
        if store is not None:store.db.engine.dispose()
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close()


def test_variant_actual_http_constraint_adjustment_policy_retest_and_old_session_intact(variant_http):
    sid,locale,module,live=variant_http
    question='住宿报销上限是多少？' if locale=='zh' else 'What is the hotel reimbursement limit per night?'
    baseline,_=live.post('tests','before','tests.create',{'query':question,'config_version':0})
    assert baseline.status_code==200,baseline.text
    first=baseline.json()['result']['test']
    missing='participants' if sid.endswith('capacity15') else 'launch_day'
    assert missing in first['config']['differences'] and '500' in first['answer']
    config=first['config']['requested']|{'version':2,'config_version':1,'freshness_guard':'warn'}
    config[missing]=15 if missing=='participants' else 5
    applied,_=live.post('actions','adapt','apply_config',{'tool':'apply_config','config':config});assert applied.status_code==200
    stale,_=live.post('tests','stale','tests.create',{'query':question,'config_version':1})
    assert stale.status_code==200
    old=stale.json()['result']['test'];assert not old['config']['differences']
    assert old['status']=='answered_with_warning' and '500' in old['answer']
    refreshed,_=live.post('actions','refresh','refresh_index',{'tool':'refresh_index'});assert refreshed.status_code==200
    tested,body=live.post('tests','retest','tests.create',{'query':question,'config_version':1});assert tested.status_code==200
    current=tested.json()['result']['test'];assert '400' in current['answer'] and current['citations'][0]['version']==2
    prior_state=live.state();prior_tests=live.http('GET',f'/sessions/{live.sid}/tests',headers=live.headers).json()
    another=LiveScenario(live.client,live.store)
    assert another.sid!=live.sid
    assert live.state()==prior_state
    assert live.http('GET',f'/sessions/{live.sid}/tests',headers=live.headers).json()==prior_tests
    assert another.state()['business_seq']==0
    recovered=live.http('GET',f'/sessions/{live.sid}/requests/retest',headers=live.headers)
    assert recovered.status_code==200 and recovered.json()['response']==tested.json()
