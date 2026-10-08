"""Real frozen W02 policy, controlled common-store transactions (not ScenarioModule)."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from career_lab.contracts.v2 import (
    AssistantConfig,BusinessBasis,BusinessRequest,Command,ObjectRef,ProtocolError,
    assistant_config_content_hash,
)
from career_lab.api.approvals_v2 import NegotiationService,ScenarioApprovalPort
from career_lab.api.modules import ExtensionRegistry,Gateway
from career_lab.scenarios.v2.policy import evaluate_request
from career_lab.scenarios.v2.engine import ScenarioSnapshot
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import Mutation
from career_lab.storage.role_memory import object_write
from test_context import package,catalog
from test_runtime import common_store


def prepare(tmp_path,package,catalog,*,production_followups=False,work_language="zh"):
    store,auth=common_store(tmp_path,catalog)
    # Add full initial resources in a new controlled boundary session.
    view=store.view(auth)
    world,token=store.create_session(view.bindings,package.baseline('template'),dict(package.bundle.initial_resources))
    auth=store.authenticate(world.session_id,token)
    def evaluate(request,view,caller):
        snapshot=ScenarioSnapshot(view.state,request.basis.config,{}, {}, {},request_targets={request.id:request.basis.config})
        return evaluate_request(package,request,snapshot,lambda ref: False)
    port=ScenarioApprovalPort.from_w02(package,evaluate)
    if not production_followups:port=replace(port,followup_required=False)  # explicit atomic-boundary fixture only
    port=replace(port,work_language=work_language)  # Explicit locale fixture; production selects hashed package.
    service=NegotiationService(port);registry=ExtensionRegistry();registry.register(service.operation())
    def unsupported(*_):raise ProtocolError('fixture_action_unavailable')
    registry.register(service.action_operation(unsupported));gateway=Gateway(store,registry)
    return store,auth,service,gateway


def create_request(store,auth,key,amount=100,demand=50):
    view=store.view(auth)
    baseline=AssistantConfig.model_validate(next(x.content for x in view.objects if x.ref.kind=='config'))
    config=baseline.model_copy(update={'id':'proposed-'+key,'participants':demand,
                                      'work_items':('scope_filter','human_fallback'),'fallback':'human'})
    request=BusinessRequest(id=key,session_id=auth.session_id,version=1,requested={'capacity':amount},reason='基于明确用户范围申请容量',
        basis=BusinessBasis(mode='proposed',config=config,content_hash=assistant_config_content_hash(config)),
        as_of=point(view.state),executor=auth.executor)
    write=object_write('business_request',request)
    cmd=Command(schema_version=2,request_id='create-'+key,operation='fixture_request',expected_version=view.state.business_seq,
                expected_workspace_revision=view.state.workspace_revision)
    store.execute(auth,cmd,lambda *_:Mutation(writes=(write,)))
    return write.ref


def command(store,auth,key,operation,payload):
    view=store.view(auth)
    return Command(schema_version=2,request_id=key,operation=operation,expected_version=view.state.business_seq,
                   expected_workspace_revision=view.state.workspace_revision,payload=payload)


def test_real_policy_counter_accept_atomicity_and_static_replay(tmp_path,package,catalog):
    store,auth,service,gateway=prepare(tmp_path,package,catalog)
    ref=create_request(store,auth,'capacity')
    cmd=command(store,auth,'offer','approvals.resolve',{'request':ref.model_dump(mode='json'),'expected_request_revision':1})
    offer=gateway.dispatch(auth,'approvals.resolve',cmd.model_dump(mode='json'))
    assert offer['result']['decision']['status']=='countered'
    assert offer['result']['decision']['countered']=={'capacity':60}
    assert store.view(auth).state.resources['capacity']==30
    assert offer['events'][0]['type']=='business_decided' and offer['events'][0]['data']['status']=='countered'
    subscribers={r.id for r in service.policy.roles if 'business_decided' in r.event_subscriptions}
    assert subscribers=={'supervisor','tech_lead'}
    restored=gateway.request_result(auth,'offer').model_dump(mode='json')
    assert restored['response']['events'][0]['data']==offer['events'][0]['data']
    accepted=command(store,auth,'accept','accept_counteroffer',{'tool':'accept_counteroffer','request':offer['result']['request']})
    before=store.view(auth).state
    def fault(stage):
        if stage=='after_objects':raise RuntimeError('injected atomic failure')
    with pytest.raises(RuntimeError):store.execute(auth,accepted,service.accept,approval_policy=service.acceptance_decision,fault=fault)
    assert store.view(auth).state==before
    result=gateway.dispatch(auth,'actions',accepted.model_dump(mode='json'))
    assert store.view(auth).state.resources['capacity']==60
    assert [x['type'] for x in result['events']]==['business_decided','business_counteroffer_accepted','resource_grant_committed']
    assert gateway.request_result(auth,'accept').response.events[0].data['status']=='accepted'
    assert gateway.dispatch(auth,'actions',accepted.model_dump(mode='json'))['replayed']


def test_real_policy_refuses_infeasible_counter_and_allows_new_request(tmp_path,package,catalog):
    store,auth,service,gateway=prepare(tmp_path,package,catalog)
    ref=create_request(store,auth,'impossible',100,90)
    c=command(store,auth,'reject','approvals.resolve',{'request':ref.model_dump(mode='json'),'expected_request_revision':1})
    result=gateway.dispatch(auth,'approvals.resolve',c.model_dump(mode='json'))
    assert result['result']['decision']['status']=='rejected'
    newer=create_request(store,auth,'revised',50,50)
    c=command(store,auth,'approved','approvals.resolve',{'request':newer.model_dump(mode='json'),'expected_request_revision':1})
    assert gateway.dispatch(auth,'approvals.resolve',c.model_dump(mode='json'))['result']['decision']['status']=='approved'
    old=ObjectRef.model_validate(result['result']['request']);assert store.read(auth,old).content['status']=='rejected'


def test_missing_resource_key_and_wrong_decider_are_stable_failures(tmp_path,package,catalog):
    store,auth,service,gateway=prepare(tmp_path,package,catalog)
    ref=create_request(store,auth,'request');view=store.view(auth);req=BusinessRequest.model_validate(view.get(ref).content)
    with pytest.raises(ProtocolError,match='unsupported resource request'):
        service._assess(req.model_copy(update={'requested':{'unknown':1}}),view,auth)
    original=service.policy.evaluate
    bad=NegotiationService(replace(service.policy,evaluate=lambda r,v,a:original(r,v,a).model_copy(update={'decider':'business_lead'})))
    with pytest.raises(ProtocolError,match='approval authority forbidden'):bad._assess(req,view,auth)


def test_production_w02_followup_cannot_be_silently_skipped(tmp_path,package,catalog):
    store,auth,service,gateway=prepare(tmp_path,package,catalog,production_followups=True)
    ref=create_request(store,auth,'within',50,50)
    c=command(store,auth,'approve','approvals.resolve',{'request':ref.model_dump(mode='json'),'expected_request_revision':1})
    before=store.view(auth).state
    with pytest.raises(ProtocolError,match='role decision followup unavailable'):
        gateway.dispatch(auth,'approvals.resolve',c.model_dump(mode='json'))
    assert store.view(auth).state==before


@pytest.mark.parametrize('language',['zh','en'])
def test_counteroffer_language_is_fixed_and_resource_changes_only_on_accept(tmp_path,package,catalog,language,monkeypatch):
    from career_lab.runtime.context_v2 import role_text
    store,auth,service,gateway=prepare(tmp_path,package,catalog,work_language=language)
    try:
        ref=create_request(store,auth,'localized',100,50)
        cmd=command(store,auth,'localized-offer','approvals.resolve',{'request':ref.model_dump(mode='json'),'expected_request_revision':1})
        offer=gateway.dispatch(auth,'approvals.resolve',cmd.model_dump(mode='json'))
        assert offer['result']['decision']['reason']==role_text(language,'counteroffer')
        assert offer['result']['decision']['countered']=={'capacity':60} and store.view(auth).state.resources['capacity']==30
        # UI/process locale is not a language input to business decisions.
        monkeypatch.setenv('LANG','zh_CN.UTF-8' if language=='en' else 'en_US.UTF-8')
        accept=command(store,auth,'localized-accept','accept_counteroffer',{'tool':'accept_counteroffer','request':offer['result']['request']})
        result=gateway.dispatch(auth,'actions',accept.model_dump(mode='json'))
        assert result['result']['decision']['reason']==role_text(language,'counteroffer_accepted')
        assert store.view(auth).state.resources['capacity']==60
        replay=gateway.dispatch(auth,'actions',accept.model_dump(mode='json'))
        assert replay['replayed'] and store.view(auth).state.resources['capacity']==60
        assert gateway.request_result(auth,'localized-offer').response.result['decision']['reason']==role_text(language,'counteroffer')
    finally:store.db.engine.dispose()
