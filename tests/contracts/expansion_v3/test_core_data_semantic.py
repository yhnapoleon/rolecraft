from career_lab.contracts import v2 as C
from career_lab.contracts.v2.data import semantic_decision_key,decision_key
from pydantic import ValidationError
import pytest

def pair():
    decision=C.AnnotationDecision(task_type='relation',label='SUPPORTED',applicability='applicable',evidence_ids=('e1',),acceptable_evidence_sets=(('e1',),('e2',)),evidence_evaluable=True,missing_reason='first wording')
    a=C.AnnotationPass(id='a',invocation_id='a-call',context_id='a-context',independence_method='fresh_context',executor=C.Executor(id='test',kind='system'),status='success',input_hash='0'*64,prompt_revision='p1',model_revision='test-model',evidence_order=('e1','e2'),raw_output='first synthetic output',decision=decision)
    second=decision.model_copy(update={'evidence_ids':('e2',),'missing_reason':'second wording','acceptable_evidence_sets':(('e2',),('e1',))})
    b=a.model_copy(update={'id':'b','invocation_id':'b-call','context_id':'b-context','prompt_revision':'p2','evidence_order':('e2','e1'),'raw_output':'second synthetic output','decision':second})
    return a,b

def annotate(passes,final,tier='G2v',adjudication=None):
    return C.AnnotationV2(record_id='r',annotation_version='test',input_hash='0'*64,label_tier=tier,status='accepted',passes=passes,final=final,adjudication_ref=adjudication)

def test_semantically_equal_passes_keep_first_without_fabricated_third():
    a,b=pair();assert semantic_decision_key(a.decision)==semantic_decision_key(b.decision)
    assert decision_key(a.decision)!=decision_key(b.decision)
    annotation=annotate((a,b),a.decision);assert len(annotation.passes)==2 and annotation.final==a.decision
    assert annotation.passes[1].raw_output=='second synthetic output'

@pytest.mark.parametrize('field,value',[('missing_reason','rewritten final'),('evidence_ids',('e2',))])
def test_semantic_equality_never_weakens_final_binding(field,value):
    a,b=pair();changed=a.decision.model_copy(update={field:value})
    with pytest.raises(ValidationError):annotate((a,b),changed)
    with pytest.raises(ValidationError):annotate((a,),changed,tier='G2')

@pytest.mark.parametrize('change',[{'label':'CONTRADICTED'},{'applicability':'undetermined'},{'evidence_evaluable':False},{'acceptable_evidence_sets':(('e2',),)}])
def test_real_semantic_disagreement_still_requires_actual_third_pass(change):
    a,b=pair();b=b.model_copy(update={'decision':b.decision.model_copy(update=change)})
    with pytest.raises(ValidationError):annotate((a,b),a.decision)
    third=a.model_copy(update={'id':'c','invocation_id':'c-call','context_id':'c-context','prompt_revision':'p3','raw_output':'actual synthetic adjudication'})
    ref=C.FileRef(path='labels/adjudication.json',sha256='1'*64)
    assert annotate((a,b,third),third.decision,adjudication=ref).final==third.decision
    with pytest.raises(ValidationError):annotate((a,b,third),third.decision.model_copy(update={'missing_reason':'not actual third'}),adjudication=ref)

def test_normalization_is_semantic_but_full_first_binding_stays_intact():
    a,b=pair();duplicate=b.decision.model_copy(update={'acceptable_evidence_sets':(('e1',),('e2',),('e1',))})
    assert semantic_decision_key(a.decision)==semantic_decision_key(duplicate)
    with pytest.raises(ValidationError):annotate((a,b.model_copy(update={'decision':duplicate})),duplicate)
    with pytest.raises(ValidationError):annotate((a,b.model_copy(update={'context_id':a.context_id})),a.decision)


def test_insufficient_different_explanations_keep_first_complete_decision():
    a,b=pair()
    first=a.decision.model_copy(update={'label':'INSUFFICIENT','evidence_ids':(),'acceptable_evidence_sets':((),),'missing_reason':'context lacks a dated source'})
    second=first.model_copy(update={'missing_reason':'the supplied materials do not settle the date'})
    a=a.model_copy(update={'decision':first});b=b.model_copy(update={'decision':second})
    accepted=annotate((a,b),first)
    assert C.AnnotationV2.model_validate_json(accepted.model_dump_json()).final==first
    with pytest.raises(ValidationError):annotate((a,b),second)


def test_semantic_set_order_is_normalized_and_task_namespace_is_kept():
    a,b=pair()
    first=a.decision.model_copy(update={'acceptable_evidence_sets':(('e1','e2'),('e3',))})
    reordered=first.model_copy(update={'acceptable_evidence_sets':(('e3',),('e2','e1'),('e3',))})
    assert semantic_decision_key(first)==semantic_decision_key(reordered)
    relation=first.model_copy(update={'label':'INSUFFICIENT'})
    criterion=relation.model_copy(update={'task_type':'criterion'})
    assert semantic_decision_key(relation)!=semantic_decision_key(criterion)
