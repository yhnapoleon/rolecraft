"""Release validation and human rendering for initial trial records."""
import json
from career_lab.contracts.v2 import AssistantConfig, ProtocolError, TestResultV2

CONFIG_OPTIONS = ('domains', 'scope_filter', 'update_strategy', 'fallback', 'chunk_size',
                  'retrieval_limit', 'min_score', 'freshness_guard', 'manual_domains',
                  'prohibited_topics', 'work_items', 'participants', 'launch_day')


def cell(value):
    return str(value).replace("|","\\|").replace("\n"," ").strip()


def display(value):
    if value is None:return "—"
    if isinstance(value,bool):return "true" if value else "false"
    if isinstance(value,(tuple,list)):return ", ".join(map(str,value)) or "—"
    if isinstance(value,dict):return "; ".join(f"{k}: {v}" for k,v in value.items()) or "—"
    return str(value)


def render_public_cases(records,*,locale="zh"):
    en=locale=="en"
    intro=("Preparation-stage trials, before the Product Manager handoff. Each trial uses an independent initial configuration and the same initial sources." if en else "筹备期试用：全部发生在产品经理接手前，每个试验独立采用其初始配置及同一批初始来源。")
    detail=("Answers below are excerpts. Open Trial settings and complete answers and find the same trial ID for the full answer, requested/effective settings, reasons and source versions." if en else "下表回答为节选。完整原文、请求配置、实际配置、原因码及来源版本见《试用配置与完整回答》，按同一试验编号核对。")
    table=["| Trial | Question | Answer excerpt | Status / reason | Citation |" if en else "| 试验 | 提问 | 实际回答节选 | 状态／原因码 | 引用 |", "| --- | --- | --- | --- | --- |"]
    labels={"answered":"已作答","answered_with_warning":"带警示作答","fallback":"转人工","failed":"未作答"}
    for record in records['records']:
        result=TestResultV2.model_validate(record['result'])
        answer=result.answer if len(result.answer)<=88 else result.answer[:88]+"…"
        status=result.status if en else labels[result.status]
        reason=result.error_code or ("none" if en else "无错误")
        refs="; ".join(f"{r.object_id}@{r.version}" for r in result.citations) or "—"
        table.append("| "+" | ".join(cell(x) for x in (record['trial_id'],result.query,answer,status+" / "+reason,refs))+" |")
    return [intro,detail,"\n".join(table)]


def render_case_details(records,*,locale="zh"):
    en=locale=="en"
    rows=["Each card refers to a preparation-stage trial, not a configuration in your current workspace." if en else "下列配置卡属于接手前的独立试验，不是当前工作区的配置版本。"]
    for record in records['records']:
        result=TestResultV2.model_validate(record['result']);req=result.config.requested;eff=result.config.effective
        rows.append(f"## {record['trial_id']}")
        rows.append(("Question: " if en else "提问：")+result.query)
        rows.append(("Complete actual answer: " if en else "完整实际回答：")+result.answer)
        rows.append(("Status / reason: " if en else "状态／原因码：")+result.status+" / "+(result.error_code or ("none" if en else "无错误")))
        rows.append(("Citations: " if en else "引用：")+("; ".join(f"{r.object_id}@{r.version}" for r in result.citations) or "—"))
        rows.append(("Source versions: " if en else "源版本：")+display(result.execution.source_versions)+("; Index versions: " if en else "；索引版本：")+display(result.execution.indexed_versions))
        rows.append(("Trial configuration: " if en else "试验配置标识：")+f"{req.id}; version={req.version}; config_version={req.config_version}")
        table=["| Setting | Requested | Effective |" if en else "| 参数 | 请求配置 | 实际配置 |", "| --- | --- | --- |"]
        requested=req.model_dump(mode="json");effective=eff.model_dump(mode="json")
        for key in CONFIG_OPTIONS:table.append("| "+" | ".join(cell(x) for x in (key,display(requested[key]),display(effective[key])))+" |")
        rows.append("\n".join(table))
        rows.append(("Setting differences: " if en else "参数差异：")+display(result.config.differences))
    return rows


def validate_public_cases(records, initial, materials, kb_ids, *, locale="zh"):
    if records.get('locale','zh')!=locale:raise ProtocolError('public_case_locale_mismatch')
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
