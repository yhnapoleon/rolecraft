"""Public, bilingual responsibility explanations; no inferred decisions or grades."""
from career_lab.evidence.v2.assembler import purpose_of

SCOPE = {
 'R1.target':('核对这份作品要服务谁、解决什么问题。探索阶段允许继续界定目标。','Check whom the work serves and what problem it addresses. Exploration may continue to refine the goal.'),
 'R1.metrics':('核对与本次决定相称的成功、风险或停止标准；计划中的指标不代表已有结果。','Check success, risk or stopping criteria suited to this decision. Planned metrics are not achieved results.'),
 'R2.support':('核对判断与当时可知证据的关系；引用存在不代表支持成立。','Check judgments against evidence available at the time. An existing citation does not establish support.'),
 'R2.unknowns':('区分已核事实、假设、申请和有效责任；提出尚不可行的设想不等于违约。','Separate verified facts, assumptions, requests and effective obligations. Exploring an infeasible idea is not itself a breach.'),
 'R2.failure_analysis':('核对适用的失败案例和解释；普通探索未覆盖失败分析不自动判缺失。','Review relevant failure cases and explanations. An exploratory note is not automatically deficient for omitting failure analysis.'),
 'R3.capacity':('按明确承诺的用户范围与有效容量核验；实际超限另看发生时的记录。','Check the committed user scope against effective capacity; assess actual overuse at the time it occurred.'),
 'R3.resources':('核对当前有效承诺、获批资源和时限；计划和申请不视为已执行。','Check effective commitments, approved resources and deadlines; plans and requests are not execution.'),
 'R4.functional_tests':('核对相关配置的真实测试、已核实类别及验收条件；自报类别不构成覆盖。','Check actual tests, verified categories and acceptance criteria on the relevant configuration; self-declared categories do not prove coverage.'),
 'R4.staleness_test':('核对已激活且相关的变更，以及更新后当前配置的最新动态复测；不倒扣历史作品。','Check activated relevant changes and the latest dynamic retest on the current configuration; do not judge earlier work with later facts.'),
 'R5.impact':('有相关变更时核对其影响；没有相关事件时本项不适用。','Assess impact when a relevant change exists; without a relevant event this criterion is inapplicable.'),
 'R5.adjustment':('区分实际调整、复测和文字建议；缩小范围、暂停或停止可以有合理依据。','Separate actual adjustment and retesting from a proposal; narrowing scope, pausing or stopping may be justified.'),
 'R6.consistency':('只比较同一对象、版本和责任范围；不同备选或历史版本的差异不自动算矛盾。','Compare the same subject, version and responsibility scope; different alternatives or historical versions are not automatically contradictions.'),
 'R6.operations':('核对与本次决定相称的负责人、观察窗口、退出条件和后续动作；不要求固定表单。','Check owners, observation windows, exit conditions and follow-up actions appropriate to the decision; no fixed form is required.'),
 'R6.alternatives':('核对真实的方案比较和取舍；普通文字与方案模板等价，停止也可以是备选。','Check actual comparison and trade-offs; free text and an options template are equivalent, and stopping may be an alternative.'),
}
STAGES={'exploration':('探索','exploration'),'option':('备选比较','comparison of options'),'plan':('规划','planning'),'commitment':('正式承诺','formal commitment'),'result':('结果报告','a result report')}
DECISIONS={
 'no_go':('本次声明不开展这项方案。反馈核对停止依据、替代方案和后续处置；不要求完成上线测试，也不据此判定停止合理。实际发生的行动、资源占用和完成声明仍逐项核验。',
          'You declared that this proposal will not proceed. Feedback examines the basis for stopping, alternatives and follow-up; launch tests are not required merely by this decision, and stopping is not automatically judged sound. Actual actions, resource use and completion claims remain subject to verification.'),
 'defer_with_conditions':('本次声明暂缓，待条件满足后再决定。反馈核对待确认条件、补证和重新判断的依据；暂缓不代表已经获批或已上线，实际已发生的责任仍保留。',
          'You declared a deferral pending conditions. Feedback examines unresolved conditions, evidence to collect and the basis for reconsideration. Deferral does not mean approval or launch; obligations already incurred remain.'),
 'launch_narrow':('本次声明受限开放。反馈只按明确承诺的用户范围、知识范围和固定配置核对容量、资源、测试及更新影响；没有承诺的范围不自动算交付缺失，声明也不代表实际开放或获批。',
          'You declared a limited launch. Feedback checks capacity, resources, tests and update impact against the committed users, knowledge scope and fixed configuration. Uncommitted scope is not automatically missing work; the declaration does not prove actual launch or approval.'),
 'launch':('本次声明按方案推进。反馈依据固定提交与有效约束核验承诺；声明、业务批准和实际执行分别记录。',
          'You declared that the proposal should proceed. Feedback checks commitments against the fixed submission and effective constraints; declaration, business approval and actual execution remain distinct.'),
}

def choose(pair,language):
 if language not in {'zh','en'}:raise ValueError('fixed language required')
 return pair[language=='en']

def decision_note(decision,language='zh'):
 return choose(DECISIONS[decision],language) if decision in DECISIONS else choose(('本次决定尚未明确；先保留已核实事实，不默认推进、暂缓或停止。','The decision is not specified. Retain verified facts without assuming launch, deferral or stopping.'),language)

def scope_note(criterion,language='zh'):
 return choose(SCOPE[criterion],language)

def applicability_note(policy,purpose,decision,language='zh'):
 stage=purpose_of(purpose)
 if stage is None:return choose(('作品用途未明确，本项责任待确认。','The artifact purpose is unknown; this responsibility is undetermined.'),language)
 if stage not in policy.purposes:
  return choose(('当前用途为'+STAGES[stage][0]+'，不承担本项完整验收责任。','The purpose is '+STAGES[stage][1]+', which does not carry this full acceptance obligation.'),language)
 if policy.launch_only:
  if stage=='result':return choose(('当前为结果报告，不因报告形式自动承担上线承诺；实际行动和完成声明在历史责任中核验。','A result report does not automatically imply a launch commitment; actual actions and completion claims are checked in historical responsibilities.'),language)
  if decision=='no_go':return choose(('已声明不开展，不按本项上线成功条件验收；实际已发生责任仍核验。','A no-go declaration does not carry this launch-success criterion; obligations already incurred are still checked.'),language)
  if decision=='defer_with_conditions':return choose(('已声明暂缓，不要求把未满足条件的方案视为已经上线；实际已发生责任仍核验。','Deferral does not require treating a proposal with unmet conditions as already launched; obligations already incurred are still checked.'),language)
  if decision not in {'launch','launch_narrow'}:return choose(('上线决定未明确，本项责任待确认；不默认已经开展。','No launch decision is specified; this responsibility remains undetermined and execution is not assumed.'),language)
  if decision=='launch_narrow':return choose(('本项仅核对明确承诺的受限范围及固定配置。','This criterion checks only the committed limited scope and fixed configuration.'),language)
 return scope_note(policy.id,language)
