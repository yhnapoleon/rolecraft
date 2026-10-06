"""Actual SQLite/Gateway/worker; scenario fixtures are boundary tests, not W02 QA."""
from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry, Gateway, Operation, ScenarioRegistration
from career_lab.contracts.v2 import (
    AssistantConfig, SessionBindings, ObjectRef, ProductCreate, ProductEdit, ShareCreate,
    ShareUpdate, ProductShare, WorkProductVersion, EvidenceRefV2, ExternalReference,
    ProtocolError, Command, TurnInput, digest,
)
from career_lab.jobs.repository import JobRepository
from career_lab.jobs.worker import Worker, ClaimedHandler
from career_lab.runtime.context_v2 import bare
from career_lab.runtime.roles_v2 import RoleService, create_role_service, record_reply_display
from career_lab.runtime.model_adapter import ScriptedModel, ModelReply
from career_lab.storage.role_memory import install_role_storage, read_replies
from career_lab.storage.v2_store import V2Store, Mutation, ObjectWrite, EventDraft, references
from career_lab.storage.v2_lifecycle import point
from test_context import make_catalog, scenario_state, policy_notice


def product_handler(view, cmd, auth):
    data = ProductEdit.model_validate(cmd.payload) if "product_id" in cmd.payload else ProductCreate.model_validate(cmd.payload)
    oid, version = (data.product_id, data.expected_head+1) if isinstance(data, ProductEdit) else ("product-"+cmd.request_id, 1)
    product = WorkProductVersion(product_id=oid, session_id=auth.session_id, version=version,
        cycle=view.current_cycle.ref, content=data.content, title=data.title, kind=data.kind,
        author=auth.executor, executor=auth.executor, content_hash=digest({"content": data.content, "structured_payload": None}),
        created_at=datetime.now(timezone.utc))
    ref = ObjectRef(session_id=auth.session_id, kind="product", object_id=oid, version=version)
    content=product.model_dump(mode="json")
    return Mutation(writes=(ObjectWrite(ref=ref, expected_head=version-1, content=content,
                    dependencies=references(content)),), result={"product":ref.model_dump(mode="json")})


def share_handler(view, cmd, auth):
    body = ShareCreate.model_validate(cmd.payload)
    product = ObjectRef(session_id=auth.session_id,kind="product", object_id=body.product_id, version=body.product_version)
    view.get(product)
    share=ProductShare(id="share-"+cmd.request_id, session_id=auth.session_id, version=1, product=product,
                       recipient_role=body.recipient_role, question=body.question, shared_at=point(view.state))
    ref=ObjectRef(session_id=auth.session_id,kind="share",object_id=share.id,version=1)
    return Mutation(writes=(ObjectWrite(ref=ref,expected_head=0,content=share.model_dump(mode="json"),
                    dependencies=(product,),visible_to=("learner",body.recipient_role)),),result={"share":ref.model_dump(mode="json")})


def revoke_handler(view, cmd, auth):
    body=ShareUpdate.model_validate(cmd.payload)
    old=next(r for r in view.objects if r.ref.object_id==body.share_id and r.ref.version==body.expected_revision)
    share=ProductShare.model_validate(old.content)
    share=share.model_copy(update={"version":share.version+1,"revoked_at":point(view.state)})
    ref=old.ref.model_copy(update={"version":share.version})
    return Mutation(writes=(ObjectWrite(ref=ref,expected_head=body.expected_revision,content=share.model_dump(mode="json"),
                    dependencies=(share.product,),visible_to=old.visible_to),),result={"share":ref.model_dump(mode="json")})


def build_runtime(url, model=None):
    catalog=make_catalog();store=V2Store(url);reg=ExtensionRegistry()
    bindings=SessionBindings(scenario=catalog.binding,runtime=catalog.binding,evaluation=catalog.binding)
    config=AssistantConfig(id="c0",session_id="template",domains=("faq",))
    reg.register_scenario("w04-boundary-fixture",ScenarioRegistration(bindings,config,
                          {"capacity":30,"dev_days":3},scenario_state()))
    def resolver(auth,ref,as_of,bindings):
        materials=[m for m in catalog.materials if (m.id,m.version)==(ref.object_id,ref.version)]
        if not materials or ref.session_id!=auth.session_id or (auth.allowed_objects is not None and ref.object_id not in auth.allowed_objects):
            raise ProtocolError("object_not_found",status=404)
        if isinstance(ref,EvidenceRefV2) and (ref.quote is not None or ref.span_start is not None):
            raise ProtocolError("raw_source_not_allowed",status=403)
        return ExternalReference(ref=bare(ref),source=catalog.binding,content_hash=digest(materials[0]))
    reg.register_reference_resolver("material",resolver);store.register_reference_resolver("material",resolver)
    reg.register(Operation("work_products.create","act",ProductCreate,product_handler))
    reg.register(Operation("work_products.versions.create","act",ProductEdit,product_handler))
    reg.register(Operation("work_products.shares.create","act",ShareCreate,share_handler))
    reg.register(Operation("work_products.shares.change","act",ShareUpdate,revoke_handler))
    service=create_role_service(store,catalog,model)
    service.install(reg)
    gateway=Gateway(store,reg)
    worker=Worker(JobRepository(store.db),{"v2.role_turn":ClaimedHandler(lambda payload,claim:gateway.run_job("v2.role_turn",payload,claim=claim))})
    return store,reg,gateway,worker,service


def session(runtime):
    store,reg,gateway,*_=runtime
    scenario=reg.scenarios["w04-boundary-fixture"]
    state,token=store.create_session(scenario.bindings,scenario.baseline_config,scenario.resources,scenario_state=scenario.scenario_state)
    return store.authenticate(state.session_id,token),token


def send(runtime,auth,operation,key,payload):
    store,_,gateway,*_=runtime;state=store.view(auth).state
    body={"schema_version":2,"request_id":key,"operation":operation,"expected_version":state.business_seq,
          "expected_workspace_revision":state.workspace_revision,"payload":payload}
    return gateway.dispatch(auth,operation,body),body


def test_two_shares_revoke_new_policy_and_restart_preserve_old_reply(tmp_path):
    url="sqlite:///"+str(tmp_path/"two-turns.db")
    model=ScriptedModel([ModelReply(text="旧政策需要人工核对。请先验证容量，草稿声称获批还没有决定。"),
                         ModelReply(text="上轮要求验证容量；v2补充了对照。新政策增加审批要求。"),
                         ModelReply(text="我保留此前讨论，但当前分享已撤销，不能再读取原作品。")])
    rt=build_runtime(url,model);store,_,gateway,worker,service=rt;auth,token=session(rt)
    p1,_=send(rt,auth,"work_products.create","p1",{"kind":"text","content":"方案V1：资源已获批，尚未测试"})
    product=ObjectRef.model_validate(p1["result"]["product"])
    s1,_=send(rt,auth,"work_products.shares.create","s1",{"product_id":product.object_id,"product_version":1,"recipient_role":"tech_lead"})
    share=ObjectRef.model_validate(s1["result"]["share"])
    first,body=send(rt,auth,"turns.create","t1",{"role_id":"tech_lead","text":"先咨询","shares":[share.model_dump(mode="json")]})
    assert worker.run_once()
    job=worker.jobs.get(first["result"]["queued_jobs"][0]);assert job["status"]=="completed",job
    old=read_replies(store.view(auth))[0].model_dump(mode="json")
    assert "方案V1" in json.dumps(model.calls[0],ensure_ascii=False)
    assert store.view(auth).state.resources=={"capacity":30,"dev_days":3}
    assert job["result"]["result"]["disclosures"]==[] and job["result"]["result"]["display_ack_required"]
    reply_ref=ObjectRef.model_validate(job["result"]["result"]["reply"])
    state=store.view(auth).state
    display=store.execute(auth,Command(schema_version=2,request_id="display-first",operation="turns.display",
        expected_version=state.business_seq,expected_workspace_revision=state.workspace_revision,
        payload={"ref":reply_ref.model_dump(mode="json")}),record_reply_display)
    assert len(display.result["disclosures"])==1
    assert display.result["disclosures"][0]["displayed_at_seq"]==state.business_seq
    send(rt,auth,"work_products.versions.create","p2",{"product_id":product.object_id,"expected_head":1,"kind":"text","content":"方案V2：新增对照测试，资源待批"})
    s2,_=send(rt,auth,"work_products.shares.create","s2",{"product_id":product.object_id,"product_version":2,"recipient_role":"tech_lead"})
    send(rt,auth,"work_products.shares.change","revoke",{"product_id":product.object_id,"share_id":share.object_id,"expected_revision":1,"operation":"revoke"})
    with pytest.raises(ProtocolError):
        service.port.capture(auth,TurnInput(role_id="tech_lead",text="再读旧版",shares=(share,)))
    # Scenario-event fixture uses the public atomic Mutation, with a real event.
    state=store.view(auth).state
    def update(view,cmd,a):
        old=view.private_scenario_state
        new=old.model_copy(update={"version":old.version+1,"source_versions":old.source_versions|{"policy":2},
             "material_activation":old.material_activation|{"policy:2":view.state.business_seq+1}})
        ref=ObjectRef(session_id=a.session_id,kind="scenario_state",object_id=old.id,version=new.version)
        return Mutation(writes=(ObjectWrite(ref=ref,expected_head=old.version,content=new.model_dump(mode="json"),
                      visible_to=("system",),dependencies=(old.current_config,)),),
                      events=(EventDraft(type="policy_updated",visible_to=("learner","tech_lead")),))
    event_result=store.execute(auth,Command(schema_version=2,request_id="policy",expected_version=state.business_seq,
                  expected_workspace_revision=state.workspace_revision,operation="fixture_event"),update)
    # Feed the actual returned event identity/seq through the boundary fixture.
    # Production event reading remains W04-S03, pending W01's public port.
    notice=policy_notice(auth.session_id,event_result.events[0].seq)
    notice=replace(notice,ref=notice.ref.model_copy(update={"object_id":event_result.events[0].id}))
    service.port.event_reader=lambda *_:(notice,)
    second,_=send(rt,auth,"turns.create","t2",{"role_id":"tech_lead","text":"新版如何？","shares":[s2["result"]["share"]]})
    worker.run_once();assert worker.jobs.get(second["result"]["queued_jobs"][0])["status"]=="completed"
    second_prompt=json.dumps(model.calls[1],ensure_ascii=False)
    assert "方案V2" in second_prompt and "旧政策需要人工核对" in second_prompt and "新政策增加审批要求" in second_prompt
    assert "historical_reply" in second_prompt
    send(rt,auth,"work_products.shares.change","revoke2",{"product_id":product.object_id,"share_id":s2["result"]["share"]["object_id"],"expected_revision":1,"operation":"revoke"})
    # A new ContextPort/process reconstructs memory solely from common persisted objects.
    fresh=build_runtime(url,model);fresh_auth=fresh[0].authenticate(auth.session_id,token)
    fresh[4].port.event_reader=lambda *_:(notice,)
    third,_=send(fresh,fresh_auth,"turns.create","t3",{"role_id":"tech_lead","text":"接续上轮"})
    fresh[3].run_once();assert fresh[3].jobs.get(third["result"]["queued_jobs"][0])["status"]=="completed"
    assert read_replies(fresh[0].view(fresh_auth))[0].model_dump(mode="json")==old
    restored=fresh[2].request_result(fresh_auth,"t1");assert restored.status=="completed"
    assert restored.jobs[0].effect.result["text"]==old["text"]
    count=len(model.calls)
    replay=fresh[2].dispatch(fresh_auth,"turns.create",body)
    assert replay["replayed"] and len(model.calls)==count


def test_worker_timeout_retry_is_real_and_has_no_false_reply(tmp_path):
    class Flaky:
        revision="controlled-timeout"
        def __init__(self):self.n=0
        def complete(self,*_):
            self.n+=1
            if self.n<3:raise TimeoutError("RAW_PRIVATE_CONNECTOR_5F provider details")
            return ModelReply(text="需要先做对照验证。")
    model=Flaky();rt=build_runtime("sqlite:///"+str(tmp_path/"retry.db"),model);auth,_=session(rt)
    started,_=send(rt,auth,"turns.create","retry",{"role_id":"tech_lead","text":"验证方式"})
    worker=rt[3];jid=started["result"]["queued_jobs"][0]
    worker.run_once();job=worker.jobs.get(jid)
    assert job["status"]=="queued" and job["error"]=="RoleModelUnavailable"
    assert not read_replies(rt[0].view(auth))
    worker.run_once();worker.run_once()
    assert worker.jobs.get(jid)["status"]=="completed" and model.n==3
    assert len(read_replies(rt[0].view(auth)))==1
    assert rt[0].view(auth).state.resources=={"capacity":30,"dev_days":3}


def test_public_api_uses_frozen_gateway_and_old_turns_still_work(tmp_path):
    from fastapi.testclient import TestClient
    url="sqlite:///"+str(tmp_path/"api.db");rt=build_runtime(url,ScriptedModel([ModelReply(text="先核对来源。")]))
    app=create_app(url,extensions=rt[1]);install_role_storage(app.state.v2_store)
    with TestClient(app) as client:
        created=client.post("/sessions",json={"schema_version":2,"scenario":"w04-boundary-fixture"}).json()
        sid=created["session_id"];headers={"Authorization":"Bearer "+created["token"]}
        response=client.post(f"/sessions/{sid}/turns",headers=headers,json={"schema_version":2,"request_id":"api-turn",
                            "expected_version":0,"expected_workspace_revision":0,"operation":"turns.create",
                            "payload":{"role_id":"tech_lead","text":"先核对"}})
        assert response.status_code==200,response.text
        worker=Worker(app.state.jobs,app.state.handlers);worker.run_once()
        job=client.get(f"/sessions/{sid}/jobs/"+response.json()["result"]["queued_jobs"][0],headers=headers)
        assert job.json()["status"]=="completed",job.text
        recovered=client.get(f"/sessions/{sid}/requests/api-turn",headers=headers).json()
        assert recovered["status"]=="completed"
        assert "internal_" not in json.dumps(recovered)
        # v1 path continues to queue through the original handler.
        old=client.post("/sessions",json={}).json()
        old_turn=client.post(f"/sessions/{old['session_id']}/turns",headers={"Authorization":"Bearer "+old["token"]},
                    json={"request_id":"old","role_id":"supervisor","text":"资源如何"})
        assert old_turn.status_code==200,old_turn.text


def test_other_role_cannot_read_private_share_or_chat(tmp_path):
    rt=build_runtime("sqlite:///"+str(tmp_path/"roles.db"),ScriptedModel([ModelReply(text="技术私聊：保留需要验证的问题。")]))
    auth,_=session(rt)
    product,_=send(rt,auth,"work_products.create","private",{"kind":"text","content":"TECH_ONLY_DRAFT_MARKER"})
    ref=product["result"]["product"]
    share,_=send(rt,auth,"work_products.shares.create","private-share",{"product_id":ref["object_id"],"product_version":1,"recipient_role":"tech_lead"})
    share_ref=ObjectRef.model_validate(share["result"]["share"])
    send(rt,auth,"turns.create","private-turn",{"role_id":"tech_lead","text":"技术专属问题","shares":[share_ref.model_dump(mode="json")]})
    rt[3].run_once()
    other=rt[4].port.capture(auth,TurnInput(role_id="business_owner",text="同一方案怎么看"))
    text=json.dumps(other.messages(auth)[0],ensure_ascii=False)
    assert "TECH_ONLY_DRAFT_MARKER" not in text and "技术私聊" not in text
    with pytest.raises(ProtocolError):
        rt[4].port.capture(auth,TurnInput(role_id="business_owner",text="读取技术附件",shares=(share_ref,)))


def test_restricted_output_attempt_fails_without_saved_reply_or_provider_detail(tmp_path):
    model=ScriptedModel([ModelReply(text="NEVER_W02_7C9E"),ModelReply(text="RAW_PRIVATE_CONNECTOR_5F"),ModelReply(text="internal_capacity_v1")])
    rt=build_runtime("sqlite:///"+str(tmp_path/"leak.db"),model);auth,_=session(rt)
    response,_=send(rt,auth,"turns.create","bad-model",{"role_id":"tech_lead","text":"公开内部信息"})
    for _ in range(3):rt[3].run_once()
    job=rt[3].jobs.get(response["result"]["queued_jobs"][0])
    assert job["status"]=="failed" and job["error"]=="RoleModelUnavailable"
    assert job["result"] is None and not read_replies(rt[0].view(auth))
    assert all("NEVER_W02_7C9E" not in json.dumps(call) for call in model.calls)
