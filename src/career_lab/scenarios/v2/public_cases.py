"""Actual independent pre-event assistant trials, never world-changing actions."""
from dataclasses import replace
from datetime import datetime, timezone
from career_lab.contracts.v2.core import AuthContext, Executor
from career_lab.contracts.v2.world import AssistantConfig, TestRequestV2
from career_lab.scenarios.v2.engine import ScenarioEngine
from career_lab.assistant.v2 import Assistant

TRIALS = (
    ('Q01', '会议室预约入口在什么地方', {}),
    ('Q02', '我的账号密码忘记了，需要重置', {}),
    ('Q03', '入职账号没有开通通知该怎么办', {}),
    ('Q04', '设备坏了想报修应该提供哪些信息', {}),
    ('Q05', '出差住宿报销一晚能报多少', {}),
    ('Q06', '出差出租车单程报销上限', {}),
    ('Q07', '今天餐费报销每天按什么额度', {}),
    ('Q08', '计划性请假提交申请需要提前多久', {}),
    ('Q09', '国内出差住宿每晚的报销上限', {'domains': ('stable_faq', 'onboarding')}),
    ('Q10', '国内出差住宿每晚的报销上限', {'update_strategy': 'realtime', 'work_items': ('realtime_sync', 'human_fallback'), 'launch_day': 10}),
    ('Q11', '国内出差住宿每晚的报销上限', {'update_strategy': 'manual_policy'}),
    ('Q12', '海王星大气的主要成分', {'fallback': 'none'}),
)




def run_pre_event_trial(package, trial_id, query, changes, *, now=None):
    sid = 'pre-event-' + trial_id
    auth = AuthContext(session_id=sid, actor_id='learner',
        executor=Executor(id='w02-pre-event-recorder', kind='system'),
        capabilities=('read', 'act'), credential_id='pre-event-recorder-only')
    state = ScenarioEngine(package).initial(sid)
    # Independent laboratory initial configuration, never apply_config in a
    # learner world. Both requested config and the full initial snapshot persist.
    config = AssistantConfig.model_validate(state.config.model_dump(mode='json') | changes | {
        'id': 'trial-' + trial_id, 'session_id': sid, 'version': 1, 'config_version': 0})
    state = replace(state, config=config)
    result = Assistant(package).run(state, TestRequestV2(query=query, config_version=0), auth, trial_id, now=now)
    return {'trial_id': trial_id, 'label': trial_id, 'story_phase': 'before_pm_handoff', 'locale':getattr(package,'locale','zh'),
            'input_snapshot': {'world': state.world.model_dump(mode='json'),
                'source_versions': dict(state.source_versions), 'indexed_versions': dict(state.indexed_versions),
                'material_activation': dict(state.material_activation), 'config': config.model_dump(mode='json')},
            'result': result.result.model_dump(mode='json'), 'provenance': result.provenance}


def record_public_cases(package):
    trials=TRIALS
    if getattr(package,'locale','zh')=='en':
        from .public_cases_en import TRIALS_EN
        trials=TRIALS_EN
    return {'schema_version': 2, 'locale':getattr(package,'locale','zh'), 'source_kind': 'actual_deterministic_module_run_on_synthetic_scenario',
            'story_phase': 'before_pm_handoff', 'captured_at': datetime.now(timezone.utc).isoformat(),
            'input_bundle_hash': package.content_hash, 'executor': 'system:w02-pre-event-recorder',
            'http_or_human_trial': False, 'expected_answers_included': False,
            'records': [run_pre_event_trial(package, *trial) for trial in trials]}


def record_private_diagnostic(package):
    en=getattr(package,'locale','zh')=='en'
    query = next(f.value for f in package.facts if f.id=='retrieval_probe_query' and f.version==1)
    trials = [('TR-TRAIN-01-a', query, {'min_score': .35}),
              ('TR-TRAIN-01-b', query, {'min_score': .2}),
              ('TR-TRAIN-01-control', "What makes up Neptune's atmosphere?" if en else '海王星大气的主要成分', {'min_score': .2})]
    if en:trials.insert(1,('TR-TRAIN-01-current',query,{'min_score':package.baseline('diagnostic').min_score}))
    return {'diagnostic_id': 'TR-TRAIN-01', 'locale':getattr(package,'locale','zh'), 'input_bundle_hash': package.content_hash,
            'source_kind': 'actual_module_trials_on_synthetic_scenario',
            'records': [run_pre_event_trial(package, *trial) for trial in trials],
            'calibrated_threshold': False}
