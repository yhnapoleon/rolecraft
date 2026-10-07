"""Purpose-aware rule bounds for the frozen 14-item candidate.

Only assembler-verified facts enter here. User/model declarations cannot be
converted into these trusted facts; W02 owns their actual-source production.
"""
from career_lab.contracts.v2.core import EvidenceRefV2
from career_lab.contracts.v2.evaluation import FeedbackItem, RuleBound

def run_rules_v2(item,*,work_language='zh'):
 ctx=item.rule_context;facts=ctx['facts'];proofs=ctx['fact_refs'];kind=ctx['mechanism'][3:]
 from career_lab.evidence.v2.assembler import purpose_of
 stage=purpose_of(item.purpose)
 en=work_language=='en'
 def words(zh,english):return english if en else zh
 def pending(zh='证据或语义尚未核实；保留未知，不按作品形式或未见记录判错。',english='Evidence or semantics remain unverified; neither format nor absent observations imply failure.'):
  return FeedbackItem(criterion=item.criterion,label='INSUFFICIENT',applicability='applicable',source='pending',explanation=words(zh,english),citations=())
 def has(name,typ):
  value=facts.get(name)
  return bool(proofs.get(name)) and (type(value) is typ if typ in (bool,int) else isinstance(value,typ))
 def flag(name):return has(name,bool) and facts[name] is True
 def count(name):return has(name,int) and facts[name]>=0
 def result(label,zh,english,names=(),upper=None,extra=(),na=False,lower=None):
  refs=[EvidenceRefV2.model_validate(r) for n in names for r in proofs[n]]+list(extra)
  refs=tuple({r.model_dump_json():r for r in refs}.values())
  return FeedbackItem(criterion=item.criterion,label=label,applicability='not_applicable' if na else 'applicable',source='verified_rule',
   explanation=words(zh,english),citations=refs,rule_bound=None if na else RuleBound(lower=lower or label,upper=upper or label))
 def upper_partial(zh,en,names):return result('PARTIAL',zh,en,names,lower='NOT_MET')
 content=flag('content_review_complete')
 if kind=='target' and stage in {'commitment','result'}:
  names=('target_present','business_goal_present')
  if content and all(has(n,bool) for n in names) and not all(facts[n] for n in names):
   return result('NOT_MET','完整内容核验确认目标用户或业务目标缺失；停止决定本身不触发此结论。','Complete content review confirms a missing target user or business goal; a no-go decision itself does not trigger this finding.',(*names,'content_review_complete'))
 if kind=='metrics' and stage in {'commitment','result'} and content and count('metrics_count'):
  if facts['metrics_count']==0:return result('NOT_MET','完整内容核验确认未给出指标。','Complete content review confirms no metrics.',('metrics_count','content_review_complete'))
  names=('metric_definitions_complete','metric_targets_complete')
  if all(has(n,bool) for n in names) and not all(facts[n] for n in names):return upper_partial('指标定义或目标有缺口，规则只确定上界。','Metric definitions or targets have a verified gap; only an upper bound is established.',(*names,'metrics_count','content_review_complete'))
 if kind=='unknowns' and flag('current_obligation_verified') and flag('unapproved_resource_excess'):
  return result('NOT_MET','已核实当前生效责任所需资源超过有效值且未获批准。','A current binding obligation exceeds effective resources without approval.',('current_obligation_verified','unapproved_resource_excess'))
 if kind=='failure_analysis' and stage in {'commitment','result'} and flag('failure_evidence_complete') and count('failure_evidence_count') and facts['failure_evidence_count']==0:
  return upper_partial('完整案例引用/复现记录中未见失败案例；失败模式解释仍待语义核验。','The complete citation/reproduction ledger contains no failure case; failure-mode reasoning still needs semantic review.',('failure_evidence_complete','failure_evidence_count'))
 if kind in {'capacity','resources'}:
  from .rules import run_rules
  raw=item.model_dump(mode='json',exclude={'input_hash'});raw['rule_context']={**ctx,'mechanism':kind}
  from career_lab.contracts.v2.core import digest
  from career_lab.contracts.v2.evaluation import EvidencePackageV2
  raw['input_hash']=digest(raw)
  return run_rules(EvidencePackageV2.model_validate(raw),work_language=work_language)
 if kind=='functional_tests':
  if not ctx['logs_complete'] or not ctx.get('test_sources_complete',True) or not flag('test_ledger_complete') or ctx['config_version'] is None:return pending()
  tests=[t for t in ctx['tests'] if t['record']['config']['effective']['config_version']==ctx['config_version']]
  actual=[t for t in tests if t['record']['status']!='failed']
  if not actual:
   if ctx['technical_failures'] or tests:return pending()
   return result('NOT_MET','完整记录内没有当前配置的实际测试。','The complete ledger contains no actual test on the current configuration.',('test_ledger_complete',))
  extra=tuple(EvidenceRefV2.model_validate(t['ref']) for t in actual)
  if not flag('functional_classification_complete') or not has('functional_categories_verified',list) or any(not isinstance(v,str) for v in facts['functional_categories_verified']):return pending('已有当前配置的实际运行；类别与验收标准尚待核实。','Actual runs exist on this configuration; categories and acceptance criteria remain unverified.')
  categories=set(facts['functional_categories_verified']);names=('functional_categories_verified','functional_classification_complete')
  if not has('acceptance_criteria_verified',bool):return pending()
  if len(categories)>=2 and flag('acceptance_criteria_verified'):
   return result('MET','实际测试覆盖至少两类已核验需求，并有已核验验收标准；不使用自报类别计数。','Actual tests cover at least two verified categories with verified acceptance criteria; self-declared categories are excluded.',(*names,'acceptance_criteria_verified'),extra=extra)
  return result('PARTIAL','已有实际测试；已核验类别或验收标准未覆盖全部要求。','Actual tests exist; verified categories or acceptance criteria do not cover all requirements.',(*names,'acceptance_criteria_verified'),extra=extra)
 if kind in {'impact','staleness_test','adjustment'}:
  if not flag('change_log_complete') or not has('policy_changed',bool):return pending()
  if not facts['policy_changed']:
   return result('NOT_APPLICABLE','完整记录确认该时点尚无政策变更。','The complete ledger confirms no policy change at this time.',('change_log_complete','policy_changed'),na=True)
  if not has('change_affects_subject',bool):return pending()
  if not facts['change_affects_subject']:
   return result('NOT_APPLICABLE','已核实变更不影响当前评价对象。','The verified change does not affect this subject.',('policy_changed','change_affects_subject'),na=True)
  if kind=='impact':return pending('已发生影响当前对象的变更；影响范围解释等待语义核验。','A change affecting this subject occurred; its explained impact awaits semantic verification.')
  if not count('policy_change_seq') or facts['policy_change_seq']>item.as_of.business_seq:return pending()
  if kind=='adjustment':
   if not flag('adjustment_log_complete') or not count('adjustment_action_count'):return pending()
   if facts['adjustment_action_count']==0:
    if flag('adjustment_proposal_verified') and flag('adjustment_completion_claim_verified'):return result('PARTIAL','已核实文本提出调整，但完整动作记录尚无实际调整。','A verified text proposes adjustment, but the complete action ledger has no actual adjustment.',('policy_change_seq','adjustment_log_complete','adjustment_action_count','adjustment_proposal_verified','adjustment_completion_claim_verified'),lower='NOT_MET')
    return result('NOT_MET','已受变更影响，完整动作记录中没有配置变更、刷新或复测。','The subject is affected, but the complete ledger has no configuration change, refresh or retest.',('policy_change_seq','adjustment_log_complete','adjustment_action_count'))
  if not ctx['logs_complete'] or not ctx.get('test_sources_complete',True) or not flag('test_ledger_complete') or not flag('dynamic_classification_complete') or not has('dynamic_test_ids',list) or ctx['config_version'] is None:return pending()
  if any(not isinstance(x,str) for x in facts['dynamic_test_ids']):return pending()
  tests=[t for t in ctx['tests'] if t['record']['id'] in facts['dynamic_test_ids'] and t['record']['config']['effective']['config_version']==ctx['config_version'] and t['record']['as_of']['business_seq']>=facts['policy_change_seq']]
  names=('policy_change_seq','dynamic_test_ids','test_ledger_complete','dynamic_classification_complete')
  if not tests:
   if ctx['technical_failures']:return pending()
   return result('NOT_MET' if kind=='staleness_test' else 'PARTIAL','完整记录内没有政策更新后、当前配置的相关动态复测。','The complete ledger has no relevant dynamic retest after the update on the current configuration.',names,upper=None if kind=='staleness_test' else 'MET')
  latest=max(t['record']['as_of']['storage_revision'] for t in tests)
  chosen=[t for t in tests if t['record']['as_of']['storage_revision']==latest]
  if len(chosen)!=1 or chosen[0]['record']['status']=='failed':return pending()
  test=chosen[0];record=test['record'];versions=facts.get('affected_material_versions')
  if not has('affected_material_versions',dict) or not versions or any(not isinstance(k,str) or type(v)is not int or v<1 for k,v in versions.items()):return pending()
  used=record['execution']['used_versions']
  if any(k not in used for k in versions):return pending('最新相关测试存在，但没有足以核实受影响材料版本的使用记录。','The latest relevant test exists, but its used-source records cannot establish affected material versions.')
  fresh=all(used[k]==v for k,v in versions.items())
  extra=(EvidenceRefV2.model_validate(test['ref']),)
  if kind=='staleness_test':return result('MET' if fresh else 'PARTIAL','已核对更新后最新相关动态测试的实际使用版本：'+('当前有效。' if fresh else '仍有过期版本。'),'The latest relevant dynamic test after the update used '+('current versions.' if fresh else 'at least one stale version.'),(*names,'affected_material_versions'),extra=extra)
  if not has('passing_dynamic_test_ids',list) or not flag('adjustment_appropriate_verified'):return pending()
  passed=fresh and record['id'] in facts['passing_dynamic_test_ids']
  return result('MET' if passed else 'PARTIAL','实际调整与最新相关复测已核对：'+('复测通过。' if passed else '尚未通过。'),'Actual adjustment and the latest relevant retest are verified: '+('passed.' if passed else 'not yet passed.'),(*names,'affected_material_versions','passing_dynamic_test_ids','adjustment_action_count','adjustment_log_complete','adjustment_appropriate_verified'),extra=extra)
 if kind=='consistency' and flag('numeric_conflict_verified'):
  return upper_partial('已核实文本数值与固定配置冲突；其余一致性等待语义核验。','Verified text numbers conflict with the fixed configuration; other consistency remains semantic.',('numeric_conflict_verified',))
 if kind=='operations' and content and has('operations_fields_verified',list):
  values=facts['operations_fields_verified']
  if any(v not in {'owner','window','exit','actions'} for v in values):return pending()
  if not values:return result('NOT_MET','完整内容核验确认负责人、观察窗口、退出条件和动作均缺失。','Complete content review confirms all operational fields are missing.',('content_review_complete','operations_fields_verified'))
  if set(values)=={'owner','window','exit','actions'}:return result('PARTIAL','四项安排均有可定位内容；可执行性仍待语义核验。','All four arrangements have located content; executability still needs semantic review.',('content_review_complete','operations_fields_verified'),upper='MET')
 if kind=='alternatives':
  if flag('selected_infeasible_verified'):return upper_partial('选中方案被有效可行性探针判为不可行；取舍理由仍待核验。','The chosen option failed a valid feasibility probe; trade-off reasoning remains unverified.',('selected_infeasible_verified',))
  if content and count('alternatives_count'):
   if facts['alternatives_count']==0:return result('NOT_MET','完整内容核验确认没有方案比较，已同时检查普通文字。','Complete content review confirms no alternative comparison, including free text.',('content_review_complete','alternatives_count'))
   if facts['alternatives_count']==1:return upper_partial('只核实到一个方案；规则确定上界，不推断取舍质量。','Only one option is verified; the rule sets an upper bound, not trade-off quality.',('content_review_complete','alternatives_count'))
 return pending()


def change_observations(item,*,work_language='zh'):
 """Factual observations survive a lawful no-go's launch inapplicability."""
 if item.rule_context['mechanism'] not in {'v2.staleness_test','v2.adjustment'}:return ()
 ctx=item.rule_context;f=ctx['facts'];p=ctx['fact_refs'];en=work_language=='en';out=[]
 def add(text,names,extra=()):
  refs=[ref for name in names for ref in p[name]]+list(extra)
  out.append({'summary':text,'sources':list({str(ref):ref for ref in refs}.values())})
 if f.get('change_log_complete') is True and p.get('change_log_complete') and type(f.get('policy_changed')) is bool and p.get('policy_changed'):
  text=('Policy change recorded: '+('yes.' if f['policy_changed'] else 'none in the complete window.')) if en else '政策变更记录：'+('有已激活变更。' if f['policy_changed'] else '完整窗口内无变更。')
  add(text,('change_log_complete','policy_changed'))
 if f.get('policy_changed') is not True:return tuple(out)
 seq=f.get('policy_change_seq')
 if type(seq)is not int or seq<0 or seq>item.as_of.business_seq or not p.get('policy_change_seq'):return tuple(out)
 if item.rule_context['mechanism']=='v2.staleness_test' and ctx['logs_complete'] and ctx.get('test_sources_complete',True) and f.get('test_ledger_complete') is True and p.get('test_ledger_complete') and f.get('dynamic_classification_complete') is True and p.get('dynamic_classification_complete') and isinstance(f.get('dynamic_test_ids'),list) and p.get('dynamic_test_ids') and ctx['config_version'] is not None:
  tests=[t for t in ctx['tests'] if t['record']['id'] in f['dynamic_test_ids'] and t['record']['as_of']['business_seq']>=seq and t['record']['config']['effective']['config_version']==ctx['config_version']]
  failed=sum(t['record']['status']=='failed' for t in tests)
  text=(f'Relevant dynamic retests after the change on this configuration: {len(tests)}; technical failures: {failed}. Running does not prove success.' if en else f'政策更新后当前配置的相关动态复测：{len(tests)} 次，其中技术失败 {failed} 次；运行不代表通过。')
  add(text,('policy_change_seq','test_ledger_complete','dynamic_classification_complete','dynamic_test_ids'),[t['ref'] for t in tests])
 if item.rule_context['mechanism']=='v2.adjustment':
  count=f.get('adjustment_action_count')
  if type(count)is int and count>=0 and p.get('adjustment_action_count') and f.get('adjustment_log_complete') is True and p.get('adjustment_log_complete'):
   add(('Actual relevant configuration/refresh/retest actions after the change: ' if en else '变更后实际相关配置调整／刷新／复测动作：')+str(count)+(' (does not prove quality).' if en else ' 次；次数不证明调整质量。'),('policy_change_seq','adjustment_action_count','adjustment_log_complete'))
 return tuple(out)
