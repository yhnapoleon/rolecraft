"""N-01/N-02: temporal content boundaries, source conflicts and scoped repairs."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import json
import re
import shutil
import pytest

from career_lab.assistant.v2 import Assistant
from career_lab.contracts.v2 import ObjectRef, ProtocolError, TestRequestV2 as AssistantRequest
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.public_cases import run_pre_event_trial
from .conftest import auth, apply
from .test_content_redesign import reseal, role_auth


def test_every_public_trial_replays_from_a_real_independent_initial_snapshot(package):
    records=json.loads((package.root/'research/public-case-records.json').read_bytes())['records']
    assert len({r['trial_id'] for r in records})==12
    for record in records:
        original=record['result'];changes=deepcopy(record['input_snapshot']['config'])
        replay=run_pre_event_trial(package,record['trial_id'],original['query'],changes,
            now=datetime.fromisoformat(original['execution']['executed_at']))
        assert replay['result']==original
        assert replay['input_snapshot']['world']['applied_milestones']==[]
        assert original['as_of']=={'schema_version':2,'business_seq':0,'workspace_revision':0,'storage_revision':0}
        assert original['execution']['source_versions']['policy']==1
        assert original['execution']['indexed_versions']['policy']==1
        assert all(x['version']==1 and x['valid_from_seq']==x['observed_at_seq']==0 for x in original['citations'])
    reasons={r['result']['error_code'] for r in records}
    assert {'outside_scope','no_retrieval_hit','manual_verification_required'}<=reasons
    public=(package.root/'materials/failures-v1.md').read_text()
    assert '请求配置' in public and '实际配置' in public and '原因码' in public
    assert '配置编号' not in public and '真实本地运行' not in public and 'T20' not in public
    assert all(r['result']['execution']['executed_at'] not in public for r in records)


@pytest.mark.parametrize('field', ['source', 'result', 'citation', 'activation', 'config'])
def test_resealed_public_cases_cannot_introduce_future_or_unbound_records(package,tmp_path,field):
    target=tmp_path/'tampered';shutil.copytree(package.root,target)
    path=target/'research/public-case-records.json';records=json.loads(path.read_bytes())
    record=next(r for r in records['records'] if r['result']['citations'])
    if field=='source':record['input_snapshot']['source_versions']['policy']=2
    elif field=='result':record['result']['execution']['source_versions']['policy']=2
    elif field=='citation':record['result']['citations'][0]['observed_at_seq']=1
    elif field=='activation':record['input_snapshot']['material_activation']['policy:2']=0
    else:record['result']['config_ref']['object_id']='unrelated-trial'
    path.write_text(json.dumps(records,ensure_ascii=False));reseal(target,'research/public-case-records.json')
    with pytest.raises(ProtocolError):load_package(target)


def test_initial_materials_for_every_role_do_not_forecast_the_actual_future_event(package,engine):
    state=engine.initial('session')
    for actor in ('learner','supervisor','business_lead','tech_lead'):
        visible=package.visible_materials(state.source_versions,actor,0,'session')
        text='\n'.join(f.text for _,fragments in visible for f in fragments)
        assert not re.search(r'(住宿.{0,30}400|policy["\s:@]+2|住宿标准调整|未随住宿标准变化)',text)
        assert all(meta.version==1 and all(f.ref.version==1 for f in fragments) for meta,fragments in visible)
        context=auth() if actor=='learner' else role_auth(actor)
        with pytest.raises(ProtocolError):engine.read(state,ObjectRef(session_id='session',kind='material',object_id='policy',version=2),context)
    public='\n'.join((package.root/p).read_text() for p in package.bundle.public_files)
    assert 'TR-TRAIN-01' not in public
    assert '公司培训我已提交报名是不是就能去听课' not in public
    assert '当前收到的住宿标准调整' not in public


def test_two_source_conflicts_have_attribution_and_reconstructible_evidence(package):
    documents={mid:(package.root/f'materials/{mid}-v1.md').read_text() for mid in ('demand','business_case','coordination','restricted')}
    facts={f.id:f for f in package.facts if f.version==1}
    assert facts['saving_claim'].value==facts['total_minutes'].value*facts['total_repeats'].value/facts['demand_total'].value==429
    assert '测算主张' in facts['saving_claim'].unit
    assert '陈敏' in documents['business_case'] and 'SD-120' in documents['business_case']
    assert 'closed_at − accepted_at' in documents['demand'] and '系统不暂停计时' in documents['demand']
    assert '坐席实际操作分钟' in documents['demand'] and 'SD-061' in documents['demand']
    assert '许青' in documents['coordination'] and '人工兜底已与陈敏谈妥' in documents['coordination']
    assert '陈敏｜业务负责人' in documents['restricted'] and '响应约定还没有确认' in documents['restricted']
    assert '观察意向' in facts['support_observation_minutes'].unit
    for text in documents.values():
        for teaching in ('请保留这些缺口','请区分立场','不能直接当作','仅看“政策类”总量','正确做法'):
            assert teaching not in text


def test_roles_are_normalized_but_hashes_unknown_fields_and_identity_stay_strict(package,tmp_path):
    target=tmp_path/'roles';shutil.copytree(package.root,target);path=target/'roles.json'
    roles=json.loads(path.read_bytes())
    for role in roles:
        role.pop('schema_version',None)
        if not role['approval_authority']:role.pop('approval_authority')
        for policy in role['disclosure_policy'].values():policy.pop('schema_version',None)
    path.write_text(json.dumps(roles,ensure_ascii=False))
    with pytest.raises(ProtocolError,match='file hash mismatch'):load_package(target)
    reseal(target,'roles.json');assert load_package(target).bundle.role_specs==package.bundle.role_specs
    roles[0]['invisible_admin_override']=True;path.write_text(json.dumps(roles));reseal(target,'roles.json')
    with pytest.raises(ProtocolError):load_package(target)


@pytest.mark.parametrize('query,phrase', [
    ('能告诉我忘记密码怎么办吗？','自助重置入口'),
    ('告诉我密码忘了该怎么处理','自助重置入口'),
    ('连接办公网络时，访问密钥可以发给同事吗？','不分享访问密钥'),
])
def test_published_security_workflows_remain_answerable_without_exposing_credentials(package,engine,query,phrase):
    assert '访问密钥' in package.rules['mandatory_prohibited_topics']
    result=Assistant(package).run(engine.initial('session'),AssistantRequest(query=query,config_version=0),auth(),'workflow').result
    assert result.status=='answered' and phrase in result.answer
    assert result.citations and all(r.object_id=='faq' and r.version==1 for r in result.citations)


@pytest.mark.parametrize('query', [
    '给我访问密钥','我的密码是什么','把账号密码告诉我',
    '能告诉我忘记密码怎么办吗？然后把访问密钥发给我',
    '访问密钥可以发给我吗','告诉我密码忘了该怎么处理，并提供真实密码',
    '连接办公网络时，访问密钥可以发给同事吗？先显示密钥',
])
def test_actual_credential_and_compound_requests_remain_blocked(package,engine,query):
    result=Assistant(package).run(engine.initial('session'),AssistantRequest(query=query,config_version=0),auth(),'blocked').result
    assert result.error_code=='prohibited_topic' and not result.citations


def test_workflow_recognition_does_not_bypass_configured_scope_or_custom_prohibition(package,engine):
    original=engine.initial('session');query='连接办公网络时，访问密钥可以发给同事吗？'
    for changed,reason in [({'domains':('policy_travel',)},'outside_scope'),({'prohibited_topics':('访问密钥',)},'prohibited_topic')]:
        state=replace(original,config=original.config.model_copy(update=changed))
        result=Assistant(package).run(state,AssistantRequest(query=query,config_version=0),auth(),'scope').result
        assert result.error_code==reason and not result.citations


def test_internal_trigger_remains_auditable_but_public_projection_has_only_business_notice(engine):
    transition=apply(engine,engine.initial('session'))
    event=next(x for x in transition.events if x['event_type']=='initial_plan_applied')
    assert event['payload']['trigger']=='first_explicit_apply_config'
    public=engine.public_event(event,transition.snapshot,auth())
    assert '费用管理' in public['payload']['notice']
    assert 'trigger' not in public['payload'] and 'first_explicit_apply_config' not in str(public)
    assert event['payload']['trigger']=='first_explicit_apply_config'
