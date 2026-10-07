"""Release validation and human rendering for initial trial records."""
import json
from career_lab.contracts.v2 import AssistantConfig, ProtocolError, TestResultV2

CONFIG_OPTIONS = ('domains', 'scope_filter', 'update_strategy', 'fallback', 'chunk_size',
                  'retrieval_limit', 'min_score', 'freshness_guard', 'manual_domains',
                  'prohibited_topics', 'work_items', 'participants', 'launch_day')


def render_public_cases(records):
    rows = ['整理：筹备期技术试用记录。以下试验均在产品经理接手前完成，各试验单独采用所列初始配置和同一批初始来源。试验编号用于回查，不是本次工作区的配置版本。']
    for record in records['records']:
        result = TestResultV2.model_validate(record['result'])
        requested = result.config.requested.model_dump(mode='json')
        effective = result.config.effective.model_dump(mode='json')
        rows.extend([
            f"试验{record['trial_id']}｜提问：{result.query}",
            '请求配置：' + json.dumps({k: requested[k] for k in CONFIG_OPTIONS}, ensure_ascii=False, sort_keys=True),
            '实际配置：' + json.dumps({k: effective[k] for k in CONFIG_OPTIONS}, ensure_ascii=False, sort_keys=True),
            '参数差异：' + json.dumps(result.config.differences, ensure_ascii=False, sort_keys=True),
            f'实际回答：{result.answer}',
            '引用：' + ('；'.join(f'{r.object_id}@{r.version}' for r in result.citations) or '无'),
            '源版本：' + json.dumps(result.execution.source_versions, ensure_ascii=False, sort_keys=True) +
            '；索引版本：' + json.dumps(result.execution.indexed_versions, ensure_ascii=False, sort_keys=True),
            f"实际状态：{result.status}；原因码：{result.error_code or '无错误'}。",
        ])
    return rows


def validate_public_cases(records, initial, materials, kb_ids):
    if records.get('schema_version') != 2 or records.get('story_phase') != 'before_pm_handoff':
        raise ProtocolError('public_case_phase_invalid')
    trials = records.get('records', [])
    if not 10 <= len(trials) <= 15 or len({r.get('trial_id') for r in trials}) != len(trials):
        raise ProtocolError('public_case_trial_identity_invalid')
    by_material = {(m.id, m.version): m for m in materials}
    expected_versions = {mid: initial[mid] for mid in kb_ids}
    for record in trials:
        result = TestResultV2.model_validate(record['result'])
        snapshot = record['input_snapshot'];world = snapshot['world']
        config = AssistantConfig.model_validate(snapshot['config'])
        if (record['story_phase'] != 'before_pm_handoff' or world['business_seq'] != 0
                or world['workspace_revision'] != 0 or world['storage_revision'] != 0
                or world['applied_milestones'] or result.as_of.business_seq != 0
                or result.as_of.workspace_revision != 0 or result.as_of.storage_revision != 0):
            raise ProtocolError('public_case_future_event')
        if (snapshot['source_versions'] != initial or snapshot['indexed_versions'] != initial
                or snapshot['material_activation'] != {f'{mid}:{v}': 0 for mid, v in initial.items()}):
            raise ProtocolError('public_case_source_window_invalid')
        if (config != result.config.requested or config.config_version != 0 or config.version != 1
                or config.id != 'trial-' + record['trial_id'] or config.session_id != 'pre-event-' + record['trial_id']
                or result.session_id != config.session_id or world['session_id'] != config.session_id
                or result.config_ref.object_id != config.id or result.config_ref.config_version != 0
                or result.config_ref.version != 1 or result.config_ref.session_id != config.session_id):
            raise ProtocolError('public_case_config_identity_invalid')
        for mapping in (result.execution.source_versions, result.execution.indexed_versions,
                        result.execution.used_versions, record['provenance']['source_versions'],
                        record['provenance']['indexed_versions'], record['provenance']['used_versions']):
            if mapping != expected_versions:
                raise ProtocolError('public_case_future_source')
        for ref in (*result.citations, *(c.ref for c in result.execution.chunks)):
            material = by_material.get((ref.object_id, ref.version))
            if (ref.object_id not in kb_ids or initial.get(ref.object_id) != ref.version
                    or ref.observed_at_seq != 0 or ref.valid_from_seq != 0
                    or ref.session_id != result.session_id or material is None):
                raise ProtocolError('public_case_reference_window_invalid')
            if not any(f.disclosure.mode == 'public' and not f.disclosure.actors
                       and f.ref.span_start <= ref.span_start < ref.span_end <= f.ref.span_end
                       and f.text[ref.span_start-f.ref.span_start:ref.span_end-f.ref.span_start] == ref.quote
                       for f in material.fragments if f.ref.span_start is not None and ref.span_start is not None and ref.span_end is not None):
                raise ProtocolError('public_case_reference_invalid')
