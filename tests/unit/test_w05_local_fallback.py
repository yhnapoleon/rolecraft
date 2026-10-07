"""Owned per-source fallback using the real reader and no configured model."""
import json
from types import SimpleNamespace
import pytest
from career_lab.contracts.v2.core import ProtocolError,EvidenceRefV2
from career_lab.contracts.v2.requests import ReviewInput
from career_lab.api.reviews_v2 import create_review_evaluator
from test_w05_default_facts import history_payload,default_review,duty,point,bare


def row(result,criterion):return next(i for i in result['feedback']['items'] if i['criterion']==criterion)


@pytest.mark.parametrize('kind',['commitment','actual_action','completion_claim'])
def test_hidden_history_sources_are_generic_pending_without_source_metadata(tmp_path,kind):
    raw=history_payload()
    secret=duty(raw,kind,facts={'actual_participants':40,'capacity_at_action':30})
    hidden=raw['records'][-1];oid=hidden['ref']['object_id'];hidden['visible_to']=['tech_lead'];hidden['text']='SECRET-PRIVATE-REASON'
    # Multiple hidden records must not reveal private cardinality.
    raw['rule_snapshots'][0]['responsibilities']=[secret,dict(secret)]
    public=duty(raw,'actual_action',criterion='R3.resources',facts={'actual_dev_days':5,'available_dev_days_at_action':3})
    raw['rule_snapshots'][0]['responsibilities'].append(public)
    result,_,_,_=default_review(tmp_path,raw,purpose='commitment',decision='launch')
    assert row(result,'R3.capacity')['source']=='verified_rule'
    hidden_rows=[h for h in result['historical_responsibilities'] if h['criterion']=='R3.capacity']
    assert len(hidden_rows)==1 and hidden_rows[0]['kind']=='unknown' and hidden_rows[0]['occurred_at'] is None
    assert hidden_rows[0]['sources']==[]
    assert any(h['finding']=='verified_breach' for h in result['historical_responsibilities'])
    text=json.dumps(result);assert 'SECRET-PRIVATE-REASON' not in text and oid not in text


def test_missing_and_hidden_rule_proofs_have_same_safe_result_and_keep_history(tmp_path):
    raw=history_payload();raw['records'][2]['visible_to']=['tech_lead'];raw['records'][2]['text']='SECRET-RULE-LIMIT'
    raw['rule_snapshots'][0]['responsibilities']=[duty(raw,'actual_action',facts={'actual_participants':40,'capacity_at_action':30})]
    hidden,_,_,_=default_review(tmp_path,raw,purpose='commitment',decision='launch',name='hidden')
    assert row(hidden,'R3.capacity')['source']=='pending'
    assert hidden['historical_responsibilities'][0]['finding']=='verified_breach'
    raw['records']=[r for r in raw['records'] if r['ref']['object_id']!='ledger-proof']
    missing,_,_,_=default_review(tmp_path,raw,purpose='commitment',decision='launch',name='missing')
    assert hidden==missing
    assert 'SECRET-RULE-LIMIT' not in json.dumps(hidden) and 'ledger-proof' not in json.dumps(hidden)


@pytest.mark.parametrize('kind',['missing','wrong_quote','forbidden'])
def test_one_bad_product_citation_keeps_verified_rules_and_history(tmp_path,kind):
    raw=history_payload();raw['rule_snapshots'][0]['responsibilities']=[duty(raw,'actual_action',facts={'actual_participants':40,'capacity_at_action':30})]
    if kind=='missing':raw['records'][0]['declared_refs'][0]['version']=99
    elif kind=='wrong_quote':raw['records'][0]['declared_refs'][0]['quote']='不存在的原句'
    else:raw['records'][1]['visible_to']=['tech_lead']
    result,_,_,_=default_review(tmp_path,raw,purpose='commitment',decision='launch')
    assert result['pending_reason']=='declared_reference_unverified' and result['feedback'] is not None
    assert row(result,'R3.capacity')['source']=='verified_rule'
    assert result['historical_responsibilities'][0]['finding']=='verified_breach'
    assert row(result,'decision.rationale')['source']=='pending'


@pytest.mark.parametrize('failure',[RuntimeError('programming failure'),ProtocolError('invariant_failed',status=500),ProtocolError('credential_revoked_or_invalid',status=403)])
def test_programming_and_credential_errors_are_not_swallowed_as_source_unknown(tmp_path,monkeypatch,failure):
    _,reader,auth,p=default_review(tmp_path,history_payload())
    read=reader.read
    def broken(a,r,t):
        if r.object_id=='ledger-proof':raise failure
        return read(a,r,t)
    monkeypatch.setattr(reader,'read',broken)
    with pytest.raises(type(failure)) as caught:create_review_evaluator(reader).review(auth,(p,),purpose='commitment',decision='launch',requested_at=point(5))
    assert caught.value is failure


def test_subject_or_session_access_denied_still_rejects_whole_review(tmp_path):
    raw=history_payload();raw['records'][0]['visible_to']=['tech_lead']
    with pytest.raises(ProtocolError):default_review(tmp_path,raw)
    _,reader,auth,p=default_review(tmp_path,history_payload(),name='authorized')
    with pytest.raises(ProtocolError):create_review_evaluator(reader).review(auth.model_copy(update={'session_id':'other'}),(p,),purpose='result',requested_at=point(5))
    with pytest.raises(ProtocolError):create_review_evaluator(reader).review(auth.model_copy(update={'allowed_objects':('m',)}),(p,),purpose='result',requested_at=point(5))


def test_expired_reference_keeps_historical_evidence_but_is_not_effective_at_subject(tmp_path):
    raw=history_payload();raw['records'][1]['ref']['valid_until_seq']=2;raw['records'][0]['declared_refs'][0]['valid_until_seq']=2
    result,_,_,_=default_review(tmp_path,raw)
    facts=result['verified_facts']
    assert facts['exact_source_count']==1 and facts['effective_source_count']==0 and facts['expired_source_count']==1
    assert facts['references'][0]['status']=='exact_reference_verified' and facts['references'][0]['valid_at_subject'] is False
    assert '作品参照点有效0个、已失效1个' in facts['summary'][0]
    assert '历史用途' in facts['summary'][0]


def test_result_without_typed_actual_or_completion_records_is_explicitly_pending(tmp_path):
    raw=history_payload();raw['rule_snapshots'][0]['responsibilities']=[duty(raw,'commitment')]
    result,_,_,_=default_review(tmp_path,raw,purpose='result',decision='launch')
    assert result['result_record_status'] and all(x['status']=='pending' for x in result['result_record_status'])
    assert all('未提供可核验' in x['reason'] for x in result['result_record_status'])
    assert all(i['label']!='NOT_MET' for i in result['feedback']['items'])
    assert '撤回' not in result['historical_responsibilities'][0]['explanation']
    raw['rule_snapshots'][0]['responsibilities'][0]['state']='withdrawn'
    withdrawn,_,_,_=default_review(tmp_path,raw,name='withdrawn')
    assert '已撤回' in withdrawn['historical_responsibilities'][0]['explanation']


def test_handle_accepts_explicit_decision_without_changing_frozen_reviewinput(tmp_path):
    _,reader,auth,p=default_review(tmp_path,history_payload())
    request=ReviewInput(subjects=(p,),purpose='commitment',scope=(),question='请核对')
    unknown=create_review_evaluator(reader).handle(auth,request,point(5))['reviews'][0]
    explicit=create_review_evaluator(reader).handle(auth,request,point(5),decision='launch')['reviews'][0]
    assert unknown['decision'] is None and row(unknown,'R3.capacity')['source']=='pending'
    assert explicit['decision_origin']=='explicit_request' and row(explicit,'R3.capacity')['source']=='verified_rule'
    future_request=SimpleNamespace(subjects=(p,),purpose='commitment',scope=(),question='',decision='no_go')
    assert create_review_evaluator(reader).handle(auth,future_request,point(5))['reviews'][0]['decision']=='no_go'


def test_trusted_structured_decision_is_exactly_bound_and_explicit_none_remains_uncertain(tmp_path):
    raw=history_payload();p=bare(EvidenceRefV2.model_validate(raw['records'][0]['ref']))
    raw['records'][0]['structured_decision']={'value':'no_go','subject':p.model_dump(mode='json'),
        'declared_at':point(3).model_dump(mode='json'),'source':raw['records'][0]['ref']}
    _,reader,auth,p=default_review(tmp_path,raw)
    req=ReviewInput(subjects=(p,),purpose='commitment',scope=(),question='')
    inferred=create_review_evaluator(reader).handle(auth,req,point(5))['reviews'][0]
    assert inferred['decision']=='no_go' and inferred['decision_origin']=='structured_subject'
    assert row(inferred,'R3.capacity')['label']=='NOT_APPLICABLE'
    cleared=create_review_evaluator(reader).handle(auth,req,point(5),decision=None)['reviews'][0]
    assert cleared['decision'] is None and row(cleared,'R3.capacity')['source']=='pending'
    raw['records'][0]['structured_decision']['declared_at']=point(4).model_dump(mode='json')
    _,bad_reader,auth,p=default_review(tmp_path,raw,name='bad-declaration')  # explicit None skips the invalid fallback
    with pytest.raises(ProtocolError,match='structured decision binding mismatch'):create_review_evaluator(bad_reader).handle(auth,req,point(5))
