from dataclasses import replace
import json
import pytest
from career_lab.assistant.v2 import Assistant,RetrievalTuning
from career_lab.contracts.v2.core import ProtocolError
from career_lab.contracts.v2.world import TestRequestV2 as AssistantTestRequest
from .conftest import auth,apply,command


def run(package,snapshot,q="住宿报销上限是多少？",tuning=None,**declared):
    if tuning is not None:
        snapshot=replace(snapshot,config=snapshot.config.model_copy(update=dict(tuning.__dict__)))
    return Assistant(package).run(snapshot,AssistantTestRequest(query=q,config_version=snapshot.config.config_version,**declared),
        auth(snapshot.world.session_id),"test",tuning=tuning)


def test_c0_and_chunk_source_ranges(package,engine):
    s=engine.initial("session");tested=run(package,s)
    assert tested.result.config.requested.config_version==0
    assert tested.result.config.requested.version==1
    assert tested.result.status=="answered"
    assert "500" in tested.result.answer and "餐费" not in tested.result.answer
    for ref in tested.result.citations:
        text=(package.root/package.rules["material_files"][ref.object_id][str(ref.version)]).read_text()
        assert text[ref.span_start:ref.span_end]==ref.quote
    assert len(tested.provenance["chunk_ids"])==1
    assert all("private" not in key for key in tested.provenance["source_versions"])


def test_false_positive_and_prohibition_do_not_leak(package,engine):
    s=engine.initial("session")
    for q,code in [("火星天气如何？","no_retrieval_hit"),("个人薪资是多少？","prohibited_topic"),("访问密钥是什么？","prohibited_topic")]:
        execution=run(package,s,q);result=execution.result
        assert result.status=="fallback" and result.error_code==code
        assert not result.citations
        assert "NEVER_W02" not in str(execution)
    assert run(package,s,"账号忘记密码怎么办？").result.status=="answered"


def test_source_update_stale_warning_guard_and_refresh(package,engine):
    s=apply(engine,engine.initial("session")).snapshot
    old=run(package,s,tuning=RetrievalTuning(freshness_guard="warn"))
    assert old.result.status=="answered_with_warning" and "500" in old.result.answer
    assert old.provenance["source_versions"]["policy"]==2
    assert old.provenance["indexed_versions"]["policy"]==1
    guarded=run(package,s,tuning=RetrievalTuning(freshness_guard="fallback"))
    assert guarded.result.error_code=="stale_source_guard" and not guarded.result.citations
    s=engine.plan(s,command(s,"refresh_index","refresh"),auth()).snapshot
    current=run(package,s)
    assert current.result.status=="answered" and "400" in current.result.answer
    assert current.result.citations[0].valid_from_seq==2
    assert old.result.citations[0].version==1
    assert old.result.answer!=current.result.answer


def test_scope_filter_and_manual_domain_switches(package,engine):
    initial=engine.initial("session")
    scoped=replace(initial,config=initial.config.model_copy(update={"domains":("stable_faq",)}))
    assert run(package,scoped).result.error_code=="outside_scope"
    unfiltered=replace(scoped,config=scoped.config.model_copy(update={"scope_filter":False}))
    assert run(package,unfiltered).result.status=="answered"
    assert run(package,initial,tuning=RetrievalTuning(manual_domains=("policy",))).result.error_code=="manual_verification_required"
    manual=replace(initial,config=initial.config.model_copy(update={"update_strategy":"manual_policy"}))
    assert run(package,manual).result.error_code=="manual_verification_required"
    assert run(package,manual,"会议室如何预约？").result.status=="answered"


def test_real_retrieval_limits_threshold_chunk_size_and_fallback(package,engine):
    s=engine.initial("session")
    one=run(package,s,"报销上限")
    several=replace(s,config=s.config.model_copy(update={"retrieval_limit":3}))
    assert len(run(package,several,"报销上限").result.citations)>len(one.result.citations)
    assert run(package,s,tuning=RetrievalTuning(min_score=2)).result.error_code=="no_retrieval_hit"
    tiny=replace(s,config=s.config.model_copy(update={"chunk_size":10}))
    assert all(len(ref.quote)<=10 for ref in run(package,tiny).result.citations)
    nohuman=replace(s,config=s.config.model_copy(update={"fallback":"none"}))
    assert run(package,nohuman,"火星天气如何？").result.status=="failed"
    missing=replace(s,config=s.config.model_copy(update={"work_items":()}))
    noresource=run(package,missing,"火星天气如何？")
    assert noresource.result.status=="failed"
    assert noresource.result.config.differences["fallback"]=="human_fallback_not_provisioned"


def test_realtime_without_grant_reports_actual_daily_behavior(package,engine):
    s=apply(engine,engine.initial("session"),update_strategy="realtime",work_items=("realtime_sync","human_fallback"),launch_day=10).snapshot
    result=run(package,s)
    assert result.result.config.requested.update_strategy=="realtime"
    assert result.result.config.effective.update_strategy=="daily"
    assert result.result.config.differences["update_strategy"]=="realtime_sync_not_provisioned"
    assert "500" in result.result.answer


def test_declared_expectation_never_becomes_true_coverage(package,engine):
    s=engine.initial("session")
    a=run(package,s,"会议室如何预约？",declared_category="normal",declared_expected="anything")
    b=run(package,s,"会议室如何预约？",declared_category="dynamic",declared_expected="always passes")
    assert a.result.observed_coverage==b.result.observed_coverage==("stable_faq",)
    assert not b.provenance["declared_expectation_is_gold"]
    assert b.result.declared_category=="dynamic"
    assert b.result.answer==a.result.answer


def test_invalid_context_and_unknown_config(package,engine):
    s=engine.initial("session");assistant=Assistant(package)
    with pytest.raises(ProtocolError,match="config not current"):
        assistant.run(s,AssistantTestRequest(query="住宿",config_version=1),auth(),"t")
    with pytest.raises(ProtocolError,match="session forbidden"):
        assistant.run(s,AssistantTestRequest(query="住宿",config_version=0),auth("other"),"t")
    restricted=assistant.run(s,AssistantTestRequest(query="住宿",config_version=0),auth(objects=("faq","pilot")),"t")
    assert not restricted.result.citations and "policy" not in restricted.provenance["source_versions"]
    with pytest.raises(ValueError):RetrievalTuning(min_score=float("nan"))
