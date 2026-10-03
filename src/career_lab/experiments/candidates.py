import re
from career_lab.contracts.evaluation import JudgeDecision
from career_lab.datasets.scenario_matrix import TEMPLATES, FIELDS, evaluate, expression_text
from career_lab.datasets.controlled import LABEL, sufficient_sets


class RuleCandidate:
    """Only explicit capacity/resource grammar; no access to proof or gold files."""
    revision='restricted-rules-v2.1'
    families=('capacity','resources')

    def supports(self,item):
        return next((t for t in TEMPLATES if t.family in self.families and expression_text(t.expression) in item.claim and t.description in item.claim),None)

    def judge(self,item):
        if item.task_type!='relation': raise ValueError('relation only')
        template=self.supports(item)
        if template is None:
            return JudgeDecision(label='INSUFFICIENT',abstained=True,evidence_ids=(),reason_code='RULE_ABSTAIN',
                explanation='规则不覆盖该语法，需复核；这是系统弃权，不能当作材料缺失真值。',model_revision=self.revision)
        facts,ids={},{}
        for evidence in item.candidate_evidence:
            for field,name in FIELDS.items():
                match=re.fullmatch(rf'(?:{re.escape(name)}：(\d+)。|记录中的{re.escape(name)}为(\d+)。)',evidence.text)
                if match:
                    value=int(match.group(1) or match.group(2))
                    if field in facts and facts[field]!=value: raise ValueError('conflicting observed facts')
                    facts[field]=value;ids[field]=evidence.id
        from career_lab.datasets.scenario_matrix import variables
        relevant={k:v for k,v in facts.items() if k in variables(template.expression)}
        truth=evaluate(template.expression,relevant)
        sufficient=sufficient_sets(template.expression,relevant)[0]
        return JudgeDecision(label=LABEL[truth],evidence_ids=tuple(ids[k] for k in sufficient),reason_code='VERIFIED_GRAMMAR',
            explanation='按输入中明确的数值/依赖条件核验；规则和数据验证器同源，仅适用于受控语法。',model_revision=self.revision)


class HybridCandidate:
    def __init__(self,model):
        self.model=model;self.rules=RuleCandidate();self.revision='hybrid:'+self.rules.revision+':'+model.revision

    def judge(self,item):
        decision=self.rules.judge(item) if self.rules.supports(item) else self.model.judge(item)
        return decision.model_copy(update={'model_revision':self.revision})
