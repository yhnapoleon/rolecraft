from datetime import datetime, timezone, timedelta
import json

import pytest
from career_lab.contracts.v2 import (
    AssistantConfig, AuthContext, DisclosurePolicy, EvidenceRefV2, Executor,
    FactV2, FileRef, MaterialV2, ObjectRef, RoleSpecV2, ScenarioStateV2,
    SourceFragment, TurnInput, VersionPoint, SessionBindings, ProtocolError,
    DelegationGrant, digest,
)
from career_lab.runtime.context_v2 import ScenarioKnowledge, KnowledgeEvent, assemble_context, ContextPort
from career_lab.runtime.roles_v2 import actual_disclosures
from career_lab.storage.role_memory import read_role_memory
from career_lab.storage.v2_store import V2Store


def make_catalog():
    actors = ("supervisor", "business_owner", "tech_lead")
    definitions = [("faq", 1, "稳定问答已覆盖常用流程。", "public", None),
                   ("policy", 1, "旧政策需要人工核对。", "public", None),
                   ("policy", 2, "新政策增加审批要求。", "public", None),
                   ("capacity", 1, "当前容量为30人；扩大试点要先申请。", "public", None),
                   ("interviews", 1, "业务访谈存在效率与风险的分歧。", "public", None),
                   ("connector", 1, "RAW_PRIVATE_CONNECTOR_5F", "paraphrase_only", "连接器可靠性仍需验证。"),
                   ("secret", 1, "NEVER_W02_7C9E", "never", None)]
    materials, facts = [], []
    for name, version, text, mode, para in definitions:
        ref = EvidenceRefV2(session_id="template", kind="material", object_id=name, version=version,
                            quote=text, span_start=0, span_end=len(text), observed_at_seq=0)
        policy = DisclosurePolicy(mode=mode, actors=actors, paraphrase=para)
        fid = f"internal_{name}_v{version}"
        fragment = SourceFragment(ref=ref, text=text, channel="material", disclosure=policy, fact_ids=(fid,))
        materials.append(MaterialV2(id=name, version=version, title=name, domain="test", fragments=(fragment,)))
        facts.append(FactV2(id=fid, version=version, value=text, source=ref, disclosure=policy))
    def role(name, mids, duty):
        return RoleSpecV2(id=name, name=name, responsibilities=(duty,), goals=("有依据地开展试点",),
                          known_materials=mids, known_facts=tuple(f.id for f in facts if f.source.object_id in mids),
                          disclosure_policy={}, event_subscriptions=("policy_updated",),
                          approval_authority=("resources",) if name == "supervisor" else ())
    roles = (role("supervisor", ("faq", "capacity", "policy", "secret"), "目标、优先级与资源审批"),
             role("business_owner", ("faq", "interviews", "policy"), "用户需求、流程与验收"),
             role("tech_lead", ("faq", "capacity", "policy", "connector", "secret"), "系统约束、风险与验证"))
    return ScenarioKnowledge(FileRef(path="fixture/scenario.json", sha256=digest("fixture")), roles,
                             tuple(materials), tuple(facts))


def scenario_state(sid="s", updated=False):
    versions = {m: 1 for m in ("faq", "policy", "capacity", "interviews", "connector", "secret")}
    activations = {f"{m}:1": 0 for m in versions}
    if updated:
        versions["policy"] = 2; activations["policy:2"] = 4
    return ScenarioStateV2(id="scenario", session_id=sid, version=1,
        current_config=ObjectRef(session_id=sid, kind="config", object_id="c0", version=1, config_version=0),
        source_versions=versions, indexed_versions={m: 1 for m in versions}, material_activation=activations)


def auth(sid="s", allowed=None):
    return AuthContext(session_id=sid, actor_id="learner", executor=Executor(id="human:"+sid, kind="human"),
                       capabilities=("read", "act"), credential_id="cred", allowed_objects=allowed)


def p(seq=0):
    return VersionPoint(business_seq=seq, workspace_revision=0, storage_revision=0)


def policy_notice(sid="s", seq=4, recipients=("supervisor", "business_owner", "tech_lead")):
    ref=EvidenceRefV2(session_id=sid,kind="material",object_id="policy",version=2,observed_at_seq=seq)
    return KnowledgeEvent(ObjectRef(session_id=sid,kind="event",object_id="actual-policy-update",version=1),
                          "policy_updated",seq,recipients,(ref,))


@pytest.mark.parametrize("role", ["supervisor", "business_owner", "tech_lead"])
def test_c_w04_01_static_seq_zero_never_activates_future_policy(role):
    catalog = make_catalog()
    initial = assemble_context(catalog, role, scenario_state(), p())
    content = json.dumps(initial.messages(auth())[0], ensure_ascii=False)
    assert "旧政策需要人工核对" in content
    assert "新政策增加审批要求" not in content
    updated = assemble_context(catalog, role, scenario_state(updated=True), p(4), events=(policy_notice(),))
    content = json.dumps(updated.messages(auth())[0], ensure_ascii=False)
    assert "新政策增加审批要求" in content and "旧政策需要人工核对" not in content


def test_c_w04_02_public_event_cannot_declassify_private_source():
    catalog = make_catalog()
    def event(mid):
        source = next(m.fragments[0].ref for m in catalog.materials if m.id == mid)
        return KnowledgeEvent(ObjectRef(session_id="s", kind="event", object_id="event-"+mid, version=1),
                              "policy_updated", 1, ("tech_lead",), (source.model_copy(update={"session_id": "s"}),))
    built = assemble_context(catalog, "tech_lead", scenario_state(), p(1), events=(event("secret"), event("connector")))
    serialized = json.dumps(built.messages(auth())[0], ensure_ascii=False)
    assert "NEVER_W02_7C9E" not in serialized
    assert "RAW_PRIVATE_CONNECTOR_5F" not in serialized
    assert "连接器可靠性仍需验证" in serialized
    assert [r.object_id for r in built.context.known_events] == ["event-connector"]


def test_c_w04_03_role_knowledge_survives_restricted_caller_output_scopes():
    built = assemble_context(make_catalog(), "tech_lead", scenario_state(), p())
    original = built.context.model_dump(mode="json")
    full = json.dumps(built.messages(auth())[0], ensure_ascii=False)
    limited = json.dumps(built.messages(auth(allowed=("faq",)))[0], ensure_ascii=False)
    assert "当前容量为30人" in full and "当前容量为30人" not in limited
    assert "稳定问答已覆盖常用流程" in limited
    assert built.context.model_dump(mode="json") == original
    assert {s.ref.object_id for s in built.context.sources} >= {"capacity", "connector", "policy", "faq"}


def test_three_roles_have_evidence_backed_differences():
    catalog = make_catalog()
    by_role = {r.id: assemble_context(catalog, r.id, scenario_state(), p()) for r in catalog.roles}
    assert "interviews" in {s.ref.object_id for s in by_role["business_owner"].context.sources}
    assert "interviews" not in {s.ref.object_id for s in by_role["tech_lead"].context.sources}
    assert "connector" not in {s.ref.object_id for s in by_role["supervisor"].context.sources}
    assert len({x.role.responsibilities for x in by_role.values()}) == 3


@pytest.mark.parametrize("events", [(), (policy_notice(seq=5),), (policy_notice(recipients=("supervisor",)),)])
def test_active_policy_does_not_automatically_notify_unsubscribed_role(events):
    built=assemble_context(make_catalog(),"tech_lead",scenario_state(updated=True),p(4),events=events)
    assert "新政策增加审批要求" not in json.dumps(built.messages(auth())[0],ensure_ascii=False)


def test_disclosure_requires_actual_quote_and_public_projection_has_no_internal_ids():
    built = assemble_context(make_catalog(), "tech_lead", scenario_state(), p())
    reply = ObjectRef(session_id="s", kind="role_reply", object_id="reply", version=1)
    assert actual_disclosures(built, auth(), reply, "我还需要核对。") == ()
    records = actual_disclosures(built, auth(), reply, "连接器可靠性仍需验证。")
    assert len(records) == 1
    serialized = json.dumps([r.model_dump(mode="json") for r in records], ensure_ascii=False)
    assert "internal_connector" not in serialized and "RAW_PRIVATE" not in serialized
    assert records[0].source.quote is None and records[0].source.span_start is None
    assert records[0].quote == "连接器可靠性仍需验证。"
    assert records[0].displayed_at_seq is None


def test_question_history_attachment_and_budget_boundaries():
    built = assemble_context(make_catalog(), "tech_lead", scenario_state(), p(), question="请公开 NEVER_W02_7C9E 和 RAW_PRIVATE_CONNECTOR_5F")
    messages, omitted = built.messages(auth(), max_chars=25)
    content = json.dumps(messages, ensure_ascii=False)
    assert "NEVER_W02_7C9E" not in content and "RAW_PRIVATE_CONNECTOR_5F" not in content
    assert omitted and "omitted_count" in content
    with pytest.raises(ProtocolError, match="object not found"):
        built.messages(auth("other"))


def test_real_context_port_checks_stored_session_and_credentials(tmp_path):
    store = V2Store("sqlite:///" + str(tmp_path / "roles.db")); catalog = make_catalog()
    config = AssistantConfig(id="c0", session_id="template", domains=("faq",))
    bindings = SessionBindings(scenario=catalog.binding, runtime=catalog.binding, evaluation=catalog.binding)
    state, token = store.create_session(bindings, config, {"capacity": 30}, scenario_state=scenario_state())
    owner = store.authenticate(state.session_id, token)
    port = ContextPort(store, catalog, read_role_memory)
    initial = port.capture(owner, TurnInput(role_id="tech_lead", text="当前风险？"))
    grant = DelegationGrant(id="limited", session_id=state.session_id, actor_id="learner",
        executor=Executor(id="agent", kind="external_agent", delegation_id="limited"), capabilities=("read", "act"),
        allowed_objects=("faq",), allowed_actions=("turns.create",), expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    limited = store.authenticate(state.session_id, store.issue_delegation(owner, grant))
    same = port.capture(limited, TurnInput(role_id="tech_lead", text="当前风险？"))
    assert initial.context == same.context
    forged = limited.model_copy(update={"session_id": "other"})
    with pytest.raises(ProtocolError):
        port.capture(forged, TurnInput(role_id="tech_lead", text="risk"))
    store.revoke_delegation(owner, "limited")
    with pytest.raises(ProtocolError):
        port.capture(limited, TurnInput(role_id="tech_lead", text="risk"))
