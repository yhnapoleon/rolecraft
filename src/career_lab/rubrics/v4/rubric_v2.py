"""Versioned 14-criterion candidate and explicit installation for new sessions.

No defaults, live bundle mutation, history rewriting, or automatic scoring.
W02 installs these files into a new bundle; W14 binds its EvaluationBundle.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
from career_lab.contracts import v2 as C
from career_lab.evidence.v2.ports import CriterionPolicy

RUBRIC_REVISION = 'rubric-v2-candidate-1'
RULES_REVISION = 'rules-v4-rubric-v2-c1'
# id, zh responsibility, en responsibility, purposes, launch-only
CRITERIA = (
 ('R1.target','目标用户、业务目标与需求证据是否对应','Whether target users and business goals match the demand evidence','all',False),
 ('R1.metrics','成功指标是否有定义、目标与可观察口径','Whether success metrics have definitions, targets and observable measures','plan',False),
 ('R2.support','关键判断是否由当时可知的证据支持','Whether key judgments are supported by evidence available at the time','all',False),
 ('R2.unknowns','是否区分事实、假设与待确认资源','Whether facts, assumptions and unconfirmed resources are distinguished','all',False),
 ('R2.failure_analysis','是否引用或复现失败案例，并正确解释失败模式','Whether failure cases are cited or reproduced and their failure modes explained','all',False),
 ('R3.capacity','正式开放人数是否符合当时有效容量','Whether committed launch participants fit the effective capacity','commitment',True),
 ('R3.resources','正式承诺的资源和时限是否有有效依据','Whether committed launch resources and timing have valid support','commitment',True),
 ('R4.functional_tests','相关配置的实际测试是否覆盖已核验类别与验收标准','Whether actual tests on the relevant configuration cover verified categories and acceptance criteria','commitment',True),
 ('R4.staleness_test','政策更新后是否复测，最新相关动态测试是否使用有效版本','Whether testing followed a policy update and the latest relevant dynamic test used current versions','commitment',True),
 ('R5.impact','是否说明已知变更对当前方案的影响范围','Whether the effects of a known change on the current proposal are explained','plan',False),
 ('R5.adjustment','受影响后是否实际调整并复测，而非只有计划声明','Whether an affected proposal was actually adjusted and retested, beyond a stated intention','commitment',True),
 ('R6.consistency','文本、配置、实际结果与决定是否相互一致','Whether text, configuration, actual results and the decision are consistent','all',False),
 ('R6.operations','负责人、观察窗口、退出条件和后续动作是否完整可执行','Whether owner, observation window, exit conditions and follow-up actions are complete and executable','plan',False),
 ('R6.alternatives','是否比较可行替代方案，并说明取舍依据','Whether viable alternatives are compared and trade-offs explained','option',False),
)
PURPOSES = {'all':('exploration','option','plan','commitment','result'),
 'plan':('plan','commitment','result'), 'option':('option','plan','commitment','result'), 'commitment':('commitment','result')}
GUARD_ZH = '先核用途与当时时点；no_go/暂缓不自动错，真实历史责任另核。普通文字与模板等价。MET须有完整支持；PARTIAL须有具体缺口；NOT_MET须有确定反证或完整记录证明缺失；未知或语义未验证用INSUFFICIENT。可接受缩小范围、人工处理或有依据的停止。禁止按kind、数量、结论枚举或Agent使用直接给能力标签。'
GUARD_EN = 'Assess purpose and the historical time first. A no-go or deferral is not automatically wrong; assess actual historical duties separately. Free text and templates are equivalent. MET requires full support, PARTIAL a specific gap, and NOT_MET verified contradiction or complete evidence of absence; unknown or unverified semantics remain INSUFFICIENT. Narrow scope, manual handling and justified stopping are acceptable alternatives. Never infer capability from kind, counts, the decision enum or Agent use.'
# All values come from a trusted deterministic/human-verified adapter and carry
# exact authorized EvidenceRefV2 sources. Missing values are unknown, never zero.
FACT_CONTRACT = {
 'target_present':'bool; exact structured/human-verified subject content, not missing template fields',
 'business_goal_present':'bool; same subject content validation',
 'content_review_complete':'bool; all formats reviewed for this exact version and criterion',
 'metrics_count':'nonnegative int; verified metrics in content',
 'metric_definitions_complete':'bool; verified definitions',
 'metric_targets_complete':'bool; verified targets',
 'current_obligation_verified':'bool; effective obligation for this exact evaluated subject, not an exploratory proposal',
 'functional_classification_complete':'bool; complete independent category classification of relevant actual tests',
 'adjustment_appropriate_verified':'bool; actual chosen adjustment satisfies the effective constraint, never inferred from action count',
 'adjustment_completion_claim_verified':'bool; exact verified text claims adjustment was completed',
 'unapproved_resource_excess':'bool; current binding obligation only; history uses ResponsibilityFact',
 'failure_evidence_count':'nonnegative int; verified actual failure-case citations/reproductions',
 'failure_evidence_complete':'bool; complete authorized case/link/reproduction ledger',
 'participants':'nonnegative number; fixed committed config, not actual usage',
 'capacity':'nonnegative number; effective authorized capacity',
 'required_dev_days':'nonnegative number; fixed committed config',
 'available_dev_days':'nonnegative number; effective approved resource',
 'requested_launch_day':'nonnegative number; fixed commitment',
 'deadline_day':'nonnegative number; effective deadline',
 'test_ledger_complete':'bool; complete relevant test ledger',
 'functional_categories_verified':'list[str]; observed, independently verified categories on this config, never declared_category',
 'acceptance_criteria_verified':'bool; observable acceptance criteria verified for this config',
 'change_log_complete':'bool; complete authorized policy-change window',
 'policy_changed':'bool; activated event in this window, not static future material',
 'policy_change_seq':'nonnegative int; latest relevant activated event business_seq',
 'change_affects_subject':'bool; verified relevance to this exact subject/config',
 'affected_material_versions':'dict[str, positive int]; current relevant versions at evaluation time',
 'dynamic_test_ids':'list[str]; W02 verified tests for affected material/questions, not user category labels',
 'dynamic_classification_complete':'bool; all relevant tests classified for the current config/window',
 'passing_dynamic_test_ids':'list[str]; actual expectation checks on relevant tests, not declared_expected',
 'adjustment_action_count':'nonnegative int; actual affected config changes/refresh/retests after event; plans excluded',
 'adjustment_log_complete':'bool; complete relevant actual action ledger',
 'adjustment_proposal_verified':'bool; verified proposal text only, never proof of execution',
 'numeric_conflict_verified':'bool; exact text/config mismatch, not model extraction',
 'operations_fields_verified':'list[str]; owner/window/exit/actions verified in any format',
 'alternatives_count':'nonnegative int; verified semantic options in any format',
 'selected_infeasible_verified':'bool; exact chosen option rejected by valid deterministic feasibility probe',
}


# Machine-readable candidate contract. Semantic quality remains unverified
# until the actual model and independent calibration have been evaluated.
DETAILS = {
 'R1.target':(['verified_subject_content'],['missing_target_or_goal:NOT_MET','present:semantic'], 'Remove no_go failure; only final decision responsibility can establish absence.'),
 'R1.metrics':(['verified_subject_content'],['no_metrics:NOT_MET','missing_definition_or_target:NOT_MET..PARTIAL','otherwise:semantic'], 'Allow risk/cost/stop criteria; no launch metric requirement on exploration.'),
 'R2.support':(['exact_authorized_quotes'],['always:semantic'], 'Reference validity is a separate factual observation, never semantic support.'),
 'R2.unknowns':(['effective_obligation','approved_resources'],['verified_current_unapproved_excess:NOT_MET','otherwise:semantic'], 'Proposed experiments or unapproved requests do not themselves establish a breach.'),
 'R2.failure_analysis':(['failure_case_reference','actual_reproduction','complete_ledger'],['complete_no_case:NOT_MET..PARTIAL','otherwise:semantic'], 'Missing observation/template does not prove case absence.'),
 'R3.capacity':(['fixed_config','effective_capacity','actual_action_history'],['within_effective_capacity:MET','over_or_invalid_launch_count:NOT_MET','missing:unknown'], 'No-go without actual opening does not inherit launch criteria; historical overuse remains.'),
 'R3.resources':(['fixed_commitment','effective_approval','actual_action_history'],['resources_and_deadline_satisfied:MET','verified_violation:NOT_MET','missing:unknown'], 'Withdrawn unexecuted commitment is not automatically a violation; actual use remains.'),
 'R4.functional_tests':(['actual_test','verified_category','verified_acceptance','complete_ledger'],['two_verified_categories_with_acceptance:MET','verified_partial_coverage:PARTIAL','complete_no_test:NOT_MET','unverified:unknown'], 'Self-declared categories and duplicate FAQ cannot establish coverage.'),
 'R4.staleness_test':(['activated_policy_event','affected_material_versions','actual_dynamic_test'],['no_relevant_change:NA','complete_no_retest:NOT_MET','latest_current:MET','latest_stale:PARTIAL','failed_or_unknown:unknown'], 'Use submission config, affected domain and historical window; no retrospective penalty.'),
 'R5.impact':(['activated_policy_event','verified_relevance','subject_content'],['no_relevant_change:NA','otherwise:semantic'], 'Display actual change; no simulated semantic conclusion before model connection.'),
 'R5.adjustment':(['activated_policy_event','actual_adjustment','actual_retest','verified_completion_claim'],['unaffected:NA','complete_no_action:NOT_MET','appropriate_action_and_pass:MET','claim_only_proposal:NOT_MET..PARTIAL','not_yet_verified:unknown'], 'Allow justified narrowing or stopping; plans and completed actions are distinct.'),
 'R6.consistency':(['comparable_subject_text','exact_config','actual_result'],['verified_same_scope_conflict:NOT_MET..PARTIAL','otherwise:semantic'], 'Different alternatives or historical versions are not intrinsically inconsistent.'),
 'R6.operations':(['verified_content_or_linked_record'],['all_four_present:PARTIAL..MET','complete_all_missing:NOT_MET','otherwise:semantic'], 'Stop/defer use their own follow-up obligations; any artifact format can express them.'),
 'R6.alternatives':(['verified_comparison_content','authorized_feasibility_probe'],['complete_no_comparison:NOT_MET','single_option_or_verified_infeasible_choice:NOT_MET..PARTIAL','otherwise:semantic'], 'Free text equals options; hidden route whitelist or unavailable probe cannot lower bounds.'),
}

def policies(*,work_language='zh'):
 if work_language not in {'zh','en'}:raise ValueError('fixed language required')
 return tuple(CriterionPolicy(cid,(zh+'。'+GUARD_ZH if work_language=='zh' else en+'. '+GUARD_EN),
   'v2.'+cid.split('.',1)[1],PURPOSES[scope],launch) for cid,zh,en,scope,launch in CRITERIA)

def rubric_document():
 return {'revision':RUBRIC_REVISION,'rules_revision':RULES_REVISION,'mode':'advisory',
  'status':'candidate_requires_independent_review_and_technical_confirmation',
  'dimension_weights':'original_weights_pending_confirmation_no_aggregate_score',
  'rule_calibration_target':{'target':45,'scale':100,'status':'not_measured'},
  'criteria':[{'id':r[0],'dimension':r[0].split('.')[0],'evidence_types':DETAILS[r[0]][0],'rule_bounds':DETAILS[r[0]][1],'difference_from_original':DETAILS[r[0]][2],'product_basis':'W05 task specification 4.3 / project definition contextual evaluation, 2026-10-07','zh':policies(work_language='zh')[i].to_dict(),'en':policies(work_language='en')[i].to_dict()} for i,r in enumerate(CRITERIA)],
  'fact_contract':FACT_CONTRACT,'unknown_policy':'INSUFFICIENT; no invented zeros, labels or future facts'}

def rules_document():
 # The installation hash includes code, so an implementation change requires a
 # fresh EvaluationBundle. Consumers must never hot-swap old session bindings.
 files=[Path(__file__).with_name(n) for n in ('rubric_v2.py','rules_v2.py','rules.py','feedback.py','judge.py','support.py','provider.py')]
 return {'revision':RULES_REVISION,'rubric_revision':RUBRIC_REVISION,'model_retries':0,
  'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}

def install_candidate(destination):
 """Explicitly export immutable candidate files for W02/W14 bundle creation."""
 destination=Path(destination);destination.mkdir(parents=True,exist_ok=True);refs={}
 for key,body in (('rubric',rubric_document()),('rules',rules_document())):
  name=body['revision']+'.json';raw=(C.canonical(body)+'\n').encode();path=destination/name
  if path.exists():
   if path.read_bytes()!=raw:raise C.ProtocolError('candidate_file_conflict')
  else:
   with path.open('xb') as f:f.write(raw)
  refs[key]=C.FileRef(path=name,sha256=hashlib.sha256(raw).hexdigest())
 return refs

def load_installed_policies(root,evaluation,*,work_language='zh'):
 """Validate actual EvaluationBundle references, then return its 14 policies."""
 from career_lab.contracts.v2.core import read_file
 bundle=C.EvaluationBundle.model_validate_json(read_file(Path(root),evaluation))
 if bundle.mode!='advisory':raise C.ProtocolError('rubric_candidate_requires_advisory')
 for ref,expected in ((bundle.rubric,rubric_document()),(bundle.rules,rules_document())):
  if json.loads(read_file(Path(root),ref))!=expected:raise C.ProtocolError('rubric_candidate_version_mismatch')
 return policies(work_language=work_language)


def create_installed_reader(store,auth,bundle_root,*,source_reader,rule_provider,
                            submission_rule_provider=None,work_language='zh'):
 """Production factory: bound files determine policies; no seven-item fallback."""
 from career_lab.evidence.v2.store_reader import StoreEvidenceReader
 evaluation=store.query(auth,lambda view:view.bindings.evaluation)
 fixed=load_installed_policies(bundle_root,evaluation,work_language=work_language)
 reader=StoreEvidenceReader(store,auth,policies=fixed,source_reader=source_reader,
                           rule_provider=rule_provider,submission_rule_provider=submission_rule_provider)
 if reader.evaluation!=evaluation:raise C.ProtocolError('evaluation_binding_changed')
 return reader
