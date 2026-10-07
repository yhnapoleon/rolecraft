"""Predeclared dev-only ranking: evidence joint, coverage, classification, cost.

Cost is a declared execution-count proxy by default; measured latency and money
are still reported separately. No candidate with zero legal joint successes is
silently presented as an evidence-capable winner.
"""
from dataclasses import dataclass,asdict
from career_lab.contracts.v2.core import ProtocolError,digest


@dataclass(frozen=True)
class SelectionPolicy:
    version: str = "joint-first-dev-v1"
    evidence_thresholds: tuple[float,...] = (.25,.5,.75)
    alpha_grid: tuple[float,...] = (0.,.25,.5,.75,1.)
    minimum_joint: float = 0.0
    require_positive_joint: bool = True
    cost_metric: str = "candidate_evaluations_per_record"

    def validate(self):
        if self.version!="joint-first-dev-v1" or self.cost_metric!="candidate_evaluations_per_record":raise ProtocolError("selection_policy_unsupported")
        if not self.evidence_thresholds or not self.alpha_grid or any(not 0<=x<=1 for x in (*self.evidence_thresholds,*self.alpha_grid)):
            raise ProtocolError("selection_grid_invalid")
        if not 0<=self.minimum_joint<=1:raise ProtocolError("selection_gate_invalid")
        return self
    def as_dict(self):
        self.validate();value=asdict(self);return value|{"id":digest(value),"priority":["joint_correctness","coverage","macro_f1","lower_cost","stable_order"]}


def eligible(metrics,policy):
    value=metrics.get("joint_correctness")
    return value is not None and metrics.get("joint_denominator",0)>0 and value>=policy.minimum_joint and (value>0 if policy.require_positive_joint else True)


def rank_key(metrics,*,cost=1,order=0):
    def number(name):return metrics[name] if metrics.get(name) is not None else -1.
    return (number("joint_correctness"),number("coverage"),number("macro_f1"),-float(cost),-order)


def choose_dev(candidates,policy=None):
    policy=(policy or SelectionPolicy()).validate()
    allowed=[(i,c) for i,c in enumerate(candidates) if eligible(c["metrics"],policy)]
    if not allowed:return {"selected":None,"status":"no_candidate_with_legal_joint_success","policy":policy.as_dict()}
    i,winner=max(allowed,key=lambda pair:rank_key(pair[1]["metrics"],cost=pair[1].get("cost",1),order=pair[0]))
    return {"selected":winner["id"],"status":"selected_for_advisory_development_only","policy":policy.as_dict()}


def tune_evidence_threshold(model,dev,policy=None):
    """Calibrate only from dev; freeze the applied threshold in the model config."""
    from dataclasses import replace
    from career_lab.models.v3.core import training_examples
    from .metrics import grade,summarize
    policy=(policy or SelectionPolicy()).validate()
    rows=training_examples(dev,model.task_type,split="dev",require_all_classes=False)
    predictions=[model.predict(r.item) for r in rows]
    grid=[]
    for threshold in sorted(policy.evidence_thresholds,key=lambda x:(abs(x-.5),x)):
        graded=[]
        for row,p in zip(rows,predictions,strict=True):
            altered=replace(p,evidence_ids=tuple(e for e,score in p.evidence_probabilities if score>=threshold)) if p.status=="ok" else p
            graded.append(grade(row,altered))
        grid.append({"id":str(threshold),"threshold":threshold,"metrics":summarize(graded,model.task_type),"cost":1})
    choice=choose_dev(grid,policy)
    chosen=next((g for g in grid if g["id"]==choice["selected"]),None)
    model.evidence_threshold=chosen["threshold"] if chosen else .5
    return {"selection_split":"dev","status":choice["status"],"applied_threshold":model.evidence_threshold,
            "policy":policy.as_dict(),"grid":grid,"dev_input_hashes":[r.annotation.input_hash for r in rows]}
