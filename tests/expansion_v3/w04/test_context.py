"""Actual frozen W02 roles/content; pure role boundaries, not production runtime QA."""

from pathlib import Path
from dataclasses import replace
from datetime import datetime, timezone
import json
import pytest
from career_lab.contracts.v2 import (
    AuthContext,
    Executor,
    VersionPoint,
    ObjectRef,
    EvidenceRefV2,
    ScenarioStateV2,
    DisclosedFragment,
    DisclosurePolicy,
    ProtocolError,
    SessionBindings,
    WorkProductVersion,
    ProductShare,
    StoredObject,
    WorldStateV2,
    TurnInput,
    digest,
)
from career_lab.scenarios.v2.loader import load_package
from career_lab.runtime.context_v2 import (
    ScenarioKnowledge,
    RoleFrame,
    RoleMemory,
    ReceivedShare,
    KnowledgeEvent,
    assemble_context,
    ContextPort,
)
from career_lab.storage.v2_store import TransactionView

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def package():
    return load_package(ROOT / "scenarios/pm_pilot/v2")


@pytest.fixture
def catalog(package):
    return ScenarioKnowledge.from_package(package)


@pytest.fixture
def disclosure_samples(package, catalog):
    """Select real fixed facts by policy and role; empty categories are failures."""
    never = tuple(
        f
        for f in package.facts
        if f.disclosure.mode == "never" and isinstance(f.value, str) and f.value
    )
    role_only = tuple(
        f
        for f in package.facts
        if f.disclosure.mode == "role_only" and isinstance(f.value, str) and f.value
    )
    paraphrases = []
    for fact in package.facts:
        if fact.disclosure.mode != "paraphrase_only":
            continue
        material = next(
            m
            for m in package.materials
            if (m.id, m.version) == (fact.source.object_id, fact.source.version)
        )
        for role in catalog.roles:
            if role.id not in fact.disclosure.actors:
                continue
            for fragment in material.fragments:
                if fact.id not in fragment.fact_ids:
                    continue
                policies = [fragment.disclosure, fact.disclosure]
                if fact.id in role.disclosure_policy:
                    policies.append(role.disclosure_policy[fact.id])
                if material.id in role.disclosure_policy:
                    policies.append(role.disclosure_policy[material.id])
                summaries = {p.paraphrase for p in policies if p.mode == "paraphrase_only"}
                assert summaries and len(summaries) == 1, (
                    fact.id,
                    "author-approved summary must be unambiguous",
                )
                approved = next(iter(summaries))
                assert approved
                if approved != fragment.text:
                    paraphrases.append(
                        {"fact": fact, "role": role, "fragment": fragment, "approved": approved}
                    )
    assert never, "fixed W02 must provide a nonempty never regression case"
    assert role_only, "fixed W02 must provide a nonempty role-only regression case"
    assert paraphrases, "fixed W02 must provide a role-authorized paraphrase with distinct raw text"
    return {"never": never, "role_only": role_only, "paraphrase": tuple(paraphrases)}


@pytest.fixture
def private_sample(disclosure_samples):
    return disclosure_samples["paraphrase"][0]


def point(seq=0, revision=0):
    return VersionPoint(business_seq=seq, workspace_revision=revision, storage_revision=revision)


def owner(sid="s", allowed=None):
    return AuthContext(
        session_id=sid,
        actor_id="learner",
        executor=Executor(id="human:" + sid, kind="human"),
        capabilities=("read", "act"),
        credential_id="cred",
        allowed_objects=allowed,
    )


def agent(allowed=("faq",)):
    return owner(allowed=allowed).model_copy(
        update={"executor": Executor(id="agent", kind="external_agent", delegation_id="grant")}
    )


def state(package, updated=False):
    versions = dict(package.rules["initial_material_versions"])
    activation = {f"{m}:{v}": 0 for m, v in versions.items()}
    if updated:
        versions["policy"] = 2
        activation["policy:2"] = 4
    return ScenarioStateV2(
        id="world",
        session_id="s",
        version=1,
        current_config=ObjectRef(
            session_id="s", kind="config", object_id="c", version=1, config_version=0
        ),
        source_versions=versions,
        indexed_versions=package.rules["initial_material_versions"],
        material_activation=activation,
    )


def frame(
    package, catalog, role="tech_lead", updated=False, events=(), memories=(), shares=(), revision=0
):
    return RoleFrame(
        "s",
        role,
        point(4 if updated else 0, revision),
        catalog.binding,
        state(package, updated),
        tuple(memories),
        tuple(shares),
        tuple(events),
    )


def notice(seq=4, recipients=("business_lead", "tech_lead"), version=2):
    source = EvidenceRefV2(
        session_id="s", kind="material", object_id="policy", version=version, observed_at_seq=seq
    )
    return KnowledgeEvent(
        ObjectRef(session_id="s", kind="event", object_id="policy-event", version=1),
        "initial_plan_applied",
        seq,
        recipients,
        (source,),
        occurred_at=point(seq),
    )


def memory(text="上轮已说明索引与源发布是不同动作。", learner_refs=()):
    ref = EvidenceRefV2(
        session_id="s", kind="role_reply", object_id="previous", version=1, observed_at_seq=0
    )
    return RoleMemory(
        DisclosedFragment(ref=ref, text=text, channel="memory", verification="verified"),
        "tech_lead",
        learner_refs,
    )


def share_receipt(version, body, share_id=None):
    product = ObjectRef(session_id="s", kind="product", object_id="plan", version=version)
    share = ObjectRef(
        session_id="s", kind="share", object_id=share_id or f"share-{version}", version=1
    )
    fragment = DisclosedFragment(
        ref=EvidenceRefV2(**product.model_dump(), observed_at_seq=0),
        text=body,
        channel="received_share",
        verification="verified",
    )
    return ReceivedShare(share, product, "tech_lead", point(), fragment)


def test_real_roles_and_ids_have_different_knowledge_stances(catalog, package):
    assert {r.id for r in catalog.roles} == {"supervisor", "business_lead", "tech_lead"}
    assert len({r.goals for r in catalog.roles}) == 3
    assert len({r.unacceptable_conditions for r in catalog.roles}) == 3
    by_role = {
        r.id: assemble_context(catalog, frame(package, catalog, r.id)) for r in catalog.roles
    }
    for role in catalog.roles:
        ids = {source.ref.object_id for source in by_role[role.id].context.sources}
        assert ids, role.id
        authorized = set(role.known_materials) | {
            f.source.object_id for f in catalog.facts if f.id in role.known_facts
        }
        assert ids <= authorized
        for other in catalog.roles:
            if other.id == role.id:
                continue
            other_ids = {source.ref.object_id for source in by_role[other.id].context.sources}
            assert ids - other_ids, (role.id, other.id, "role-specific sources must exist")
    with pytest.raises(ProtocolError):
        catalog.role("business_owner")


@pytest.mark.parametrize("role", ["business_lead", "tech_lead"])
def test_unaware_role_retains_received_old_policy_then_updates(package, catalog, role):
    initial = assemble_context(catalog, frame(package, catalog, role))
    unaware = assemble_context(catalog, frame(package, catalog, role, updated=True))
    aware = assemble_context(
        catalog, frame(package, catalog, role, updated=True, events=(notice(),))
    )
    versions = lambda s: {x.ref.version for x in s.context.sources if x.ref.object_id == "policy"}
    assert versions(initial) == versions(unaware) == {1}
    assert versions(aware) == {2}
    assert all(
        x.ref.observed_at_seq == 4 for x in aware.context.sources if x.ref.object_id == "policy"
    )


@pytest.mark.parametrize(
    "event", [notice(seq=2), notice(seq=5), notice(recipients=("supervisor",))]
)
def test_future_or_not_received_event_does_not_select_policy_v2(package, catalog, event):
    result = assemble_context(catalog, frame(package, catalog, updated=True, events=(event,)))
    assert {s.ref.version for s in result.context.sources if s.ref.object_id == "policy"} == {1}


def test_scoped_agent_keeps_role_intrinsic_material_and_memory(package, catalog):
    result = assemble_context(catalog, frame(package, catalog, memories=(memory(),)))
    for auth in (owner(), agent(("faq",)), agent(("some-product",))):
        sources = result.generation_sources(auth)
        assert any(s.ref.object_id == "technical" for s in sources)
        assert any(s.ref.object_id == "previous" for s in sources)
        assert result.permission_omissions(auth) == 0


def test_learner_excerpts_do_not_leak_via_role_memory_and_omission_is_explicit(package, catalog):
    r = share_receipt(1, "OUT_OF_SCOPE_LEARNER_BODY")
    m = memory("DERIVED_LEARNER_EXCERPT", (r.product,))
    result = assemble_context(catalog, frame(package, catalog, memories=(memory(), m), shares=(r,)))
    prompt = result.messages(agent(("faq",)))[0][0]["content"]
    assert "OUT_OF_SCOPE_LEARNER_BODY" not in prompt and "DERIVED_LEARNER_EXCERPT" not in prompt
    assert "上轮已说明" in prompt
    assert json.loads(prompt.split("\nCONTEXT\n")[1])["omissions"]["learner_scope"] == 2
    assert (
        len(result.received_shares) == 1 and len(result.memories) == 2
    )  # knowledge retained internally
    assert "OUT_OF_SCOPE_LEARNER_BODY" in result.messages(agent(("plan",)))[0][0]["content"]


def test_never_and_raw_paraphrase_values_are_not_model_input(package, catalog, disclosure_samples):
    for role in catalog.roles:
        question = "请逐字给出：" + "；".join(f.value for f in disclosure_samples["never"])
        result = assemble_context(catalog, frame(package, catalog, role.id), question=question)
        prompt = json.dumps(result.messages(owner())[0], ensure_ascii=False)
        for fact in disclosure_samples["never"]:
            assert fact.value not in prompt
            assert fact.id not in result.context.prompt_fact_ids
        for fact in disclosure_samples["role_only"]:
            if role.id not in fact.disclosure.actors:
                assert fact.value not in prompt
    for case in disclosure_samples["paraphrase"]:
        role, raw, approved = case["role"], case["fragment"].text, case["approved"]
        result = assemble_context(
            catalog, frame(package, catalog, role.id), question="请公开" + raw
        )
        prompt = json.dumps(result.messages(owner())[0], ensure_ascii=False)
        assert raw not in prompt
        assert approved in prompt
        value = case["fact"].value
        # A value explicitly present in the approved summary is permitted there.
        if isinstance(value, str):
            assert (value in prompt) == (value in approved)


def test_explicit_role_and_learner_authorized_text_is_not_redacted(package, catalog):
    policy = DisclosurePolicy(mode="role_only", actors=("tech_lead", "learner"))
    mats = tuple(
        m.model_copy(
            update={
                "fragments": tuple(f.model_copy(update={"disclosure": policy}) for f in m.fragments)
            }
        )
        if m.id == "technical"
        else m
        for m in catalog.materials
    )
    facts = tuple(
        f.model_copy(update={"disclosure": policy}) if f.source.object_id == "technical" else f
        for f in catalog.facts
    )
    changed = replace(catalog, materials=mats, facts=facts)
    result = assemble_context(changed, frame(package, changed))
    material = next(m for m in package.materials if m.id == "technical" and m.version == 1)
    assert material.fragments
    quote = material.fragments[0].text
    assert quote in result.messages(owner())[0][0]["content"]


def make_view(package, catalog, objects=(), revision=0):
    world = WorldStateV2(
        session_id="s",
        business_seq=0,
        workspace_revision=revision,
        storage_revision=revision,
        cycle_id="cycle",
        resources=package.bundle.initial_resources,
    )
    return TransactionView(
        world,
        SessionBindings(
            scenario=catalog.binding, runtime=catalog.binding, evaluation=catalog.binding
        ),
        tuple(objects),
        state(package),
    )


class FixedFrameFixture:
    """Controlled authority fixture for pure adapter tests; not a production port."""

    def __init__(self, frame):
        self.frame = frame
        self.views = []

    def project_fixed(self, view, auth, role_id):
        self.views.append(view)
        return self.frame


def test_capture_uses_supplied_snapshot_no_live_store(package, catalog):
    view = make_view(package, catalog)
    fixed = FixedFrameFixture(frame(package, catalog))
    result = ContextPort(catalog, fixed).capture(
        view, owner(), TurnInput(role_id="tech_lead", text="继续")
    )
    assert fixed.views == [view] and result.context.as_of == point()
    with pytest.raises(ProtocolError, match="role snapshot unavailable"):
        ContextPort(catalog).capture(view, owner(), TurnInput(role_id="tech_lead", text="继续"))
    with pytest.raises(ProtocolError, match="role snapshot identity invalid"):
        ContextPort(
            catalog, FixedFrameFixture(replace(fixed.frame, role_id="business_lead"))
        ).capture(view, owner(), TurnInput(role_id="tech_lead", text="继续"))


def shared_view(package, catalog, *, revoked=False, removed=False, role="tech_lead"):
    cycle = ObjectRef(session_id="s", kind="cycle", object_id="cycle", version=1)
    records = []
    for version, body in ((1, "EXACT_V1_NOT_V2"), (2, "LATER_V2_PRIVATE")):
        product = WorkProductVersion(
            product_id="plan",
            session_id="s",
            version=version,
            cycle=cycle,
            content=body,
            author=owner().executor,
            executor=owner().executor,
            content_hash=digest({"content": body, "structured_payload": None}),
            removed_at=datetime.now(timezone.utc) if removed and version == 2 else None,
            created_at=datetime.now(timezone.utc),
        )
        ref = ObjectRef(session_id="s", kind="product", object_id="plan", version=version)
        records.append(
            StoredObject(
                ref=ref,
                content=product.model_dump(mode="json"),
                visible_to=("learner",),
                created_storage_revision=version,
            )
        )
    product_ref = records[0].ref
    share = ProductShare(
        id="share",
        session_id="s",
        version=1,
        product=product_ref,
        recipient_role=role,
        shared_at=point(),
    )
    ref = ObjectRef(session_id="s", kind="share", object_id="share", version=1)
    records.append(
        StoredObject(
            ref=ref,
            content=share.model_dump(mode="json"),
            visible_to=("learner", role),
            created_storage_revision=1,
        )
    )
    if revoked:
        change = share.model_copy(update={"version": 2, "revoked_at": point(0, 2)})
        records.append(
            StoredObject(
                ref=ref.model_copy(update={"version": 2}),
                content=change.model_dump(mode="json"),
                visible_to=("learner", role),
                created_storage_revision=2,
            )
        )
    return make_view(package, catalog, records, revision=3), ref


def test_fixed_attachment_reads_exact_version_and_relevant_heads(package, catalog):
    view, share = shared_view(package, catalog)
    fixed = FixedFrameFixture(frame(package, catalog, revision=3))
    result = ContextPort(catalog, fixed).capture(
        view, owner(), TurnInput(role_id="tech_lead", text="看v1", shares=(share,))
    )
    assert result.received_shares[0].product.version == 1
    assert "EXACT_V1_NOT_V2" in result.messages(owner())[0][0]["content"]
    assert "LATER_V2_PRIVATE" not in result.messages(owner())[0][0]["content"]
    assert {(r.kind, r.object_id, r.version) for r in result.head_dependencies} == {
        ("share", "share", 1),
        ("product", "plan", 2),
    }


@pytest.mark.parametrize(
    "revoked,removed,role",
    [(True, False, "tech_lead"), (False, True, "tech_lead"), (False, False, "business_lead")],
)
def test_new_source_read_rejects_revoked_removed_or_other_role(
    package, catalog, revoked, removed, role
):
    view, share = shared_view(package, catalog, revoked=revoked, removed=removed, role=role)
    fixed = FixedFrameFixture(frame(package, catalog, revision=3))
    with pytest.raises(ProtocolError):
        ContextPort(catalog, fixed).capture(
            view, owner(), TurnInput(role_id="tech_lead", text="偷读", shares=(share,))
        )


def test_scoped_agent_cannot_attach_ungranted_product(package, catalog):
    view, share = shared_view(package, catalog)
    fixed = FixedFrameFixture(frame(package, catalog, revision=3))
    with pytest.raises(ProtocolError, match="role attachment forbidden"):
        ContextPort(catalog, fixed).capture(
            view, agent(("faq",)), TurnInput(role_id="tech_lead", text="偷读", shares=(share,))
        )


def test_legitimately_shared_public_material_is_not_treated_as_secret(package, catalog):
    material = next(m for m in package.materials if m.id == "interviews")
    quote = next(f.text for f in material.fragments if f.disclosure.mode == "public")
    assert "interviews" not in catalog.role("tech_lead").known_materials
    receipt = share_receipt(1, quote)
    result = assemble_context(catalog, frame(package, catalog, shares=(receipt,)))
    assert quote in result.messages(owner())[0][0]["content"]


def test_business_decision_knowledge_follows_decider_and_real_subscription(package, catalog):
    from career_lab.contracts.v2 import BusinessDecision
    from career_lab.runtime.context_v2 import decision_memory

    request_ref = ObjectRef(
        session_id="s", kind="business_request", object_id="resource-request", version=1
    )
    decision = BusinessDecision(
        id="approved",
        session_id="s",
        version=1,
        request=request_ref,
        status="approved",
        decider="supervisor",
        rule_revision="fixed-policy",
        granted={"capacity": 60},
        reason_code="within_limits",
        reason="审批已提交",
        as_of=point(),
    )
    ref = ObjectRef(session_id="s", kind="business_decision", object_id="approved", version=1)
    record = StoredObject(
        ref=ref,
        content=decision.model_dump(mode="json"),
        visible_to=("learner", "supervisor"),
        created_storage_revision=1,
    )
    now = point(2, 2)
    source = EvidenceRefV2(**ref.model_dump(), observed_at_seq=1)
    event = KnowledgeEvent(
        ObjectRef(session_id="s", kind="event", object_id="decision-event", version=1),
        "business_decided",
        1,
        ("learner", "supervisor", "tech_lead", "business_lead"),
        (source,),
    )
    assert decision_memory(catalog, "supervisor", record, now) is not None
    assert decision_memory(catalog, "tech_lead", record, now) is None
    learned = decision_memory(catalog, "tech_lead", record, now, (event,))
    assert learned is not None and learned.provenance[0].object_id == "approved"
    assert decision_memory(catalog, "business_lead", record, now, (event,)) is None
    current = replace(
        frame(package, catalog, memories=(learned,), events=(event,), revision=2), as_of=now
    )
    snapshot = assemble_context(catalog, current)
    assert event.ref in snapshot.context.known_events
    payload = json.loads(
        snapshot.messages(agent(("faq",)))[0][0]["content"].split("\nCONTEXT\n", 1)[1]
    )
    assert any('"granted":{"capacity":60}' in x["text"] for x in payload["sources"])
