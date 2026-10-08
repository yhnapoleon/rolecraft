"""031 R01–R09 counterexamples; all databases/data/providers here are synthetic."""

from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import Mutation, ObjectWrite, JobRequest, references
from career_lab.storage.v2_lifecycle import record_submission, point
from career_lab.storage.v2_snapshot import SnapshotService, SnapshotPortAdapter
from career_lab.storage.v2_remap import identity_key
from career_lab.storage.v2_tables import v2_credentials, v2_transactions, v2_objects, v2_snapshots
from career_lab.jobs.repository import JobRepository, LeaseLost
from career_lab.jobs.worker import Worker, WorkerClaim, ClaimedHandler
from career_lab.api.modules import ExtensionRegistry, Gateway, Operation, ScenarioRegistration
from career_lab.api.app import create_app
from career_lab.contracts.v2.projection import (
    project_fragments,
    project_disclosures,
    verify_disclosure_quotes,
)
from .conftest import command, product_plan


def queued_product(store, auth, registry, key="q"):
    gateway = Gateway(store, registry)
    queue = JobRepository(store.db)
    cmd = command(store.view(auth), key, "save")
    job = JobRequest(
        name="v2.product",
        command=cmd.model_copy(update={"request_id": key + "-effect"}),
        context_hash="0" * 64,
    )
    result = store.execute(auth, cmd, lambda *_: Mutation(jobs=(job,)))
    return gateway, queue, result


def test_R01_old_claim_cannot_borrow_replacement_lease(foundation):
    store, auth, *_ = foundation
    registry = ExtensionRegistry()
    calls = []

    def generate(view, envelope, actor):
        calls.append(1)
        return product_plan(view, envelope.command, actor)

    registry.register_job("v2.product", generate)
    gateway, queue, _ = queued_product(store, auth, registry)
    old = queue.claim_job("old", lease_seconds=0)
    new = queue.claim_job("new")
    assert old["lease_token"] != new["lease_token"]
    with pytest.raises(C.ProtocolError, match="worker lease lost"):
        gateway.run_job("v2.product", old["payload"], claim=WorkerClaim.from_job(old))
    assert calls == [] and not any(x.ref.kind == "product" for x in store.view(auth).objects)
    result = gateway.run_job("v2.product", new["payload"], claim=WorkerClaim.from_job(new))
    assert len(calls) == 1
    queue.complete(new["id"], new["lease_token"], result)
    with pytest.raises(LeaseLost):
        queue.complete(old["id"], old["lease_token"], result)


def test_R02_submitted_feedback_is_derived_immutable_and_recoverable(foundation):
    store, auth, *_ = foundation
    registry = ExtensionRegistry()
    queue = JobRepository(store.db)
    gateway = Gateway(store, registry)
    calls = []

    def feedback(view, envelope, actor):
        calls.append(1)
        subject = C.ObjectRef.model_validate(envelope.command.payload["subject"])
        obj = C.FeedbackV2(
            id="feedback",
            session_id=actor.session_id,
            subject=subject,
            evaluation=view.bindings.evaluation,
            as_of=point(view.state),
            items=(),
            business_response="Needs evidence",
            next_options=("begin_revision",),
            verified_coverage=0,
            model_coverage=0,
        )
        return Mutation(
            writes=(
                ObjectWrite(
                    ref=C.ObjectRef(
                        session_id=actor.session_id,
                        kind="feedback",
                        object_id="feedback",
                        version=1,
                    ),
                    expected_head=0,
                    content=obj.model_dump(mode="json"),
                    dependencies=(subject,),
                ),
            )
        )

    registry.register_job("v2.feedback", feedback)
    cmd = command(store.view(auth), "submit", "submit").model_copy(
        update={"payload": C.SubmitInput(decision="no_go", products=()).model_dump(mode="json")}
    )

    def submit(view, cmd, actor):
        plan = record_submission(view, cmd, actor)
        job = JobRequest(
            name="v2.feedback",
            command=cmd.model_copy(
                update={
                    "request_id": "feedback-effect",
                    "operation": "feedback.create",
                    "payload": {"subject": plan.result["submission"]},
                }
            ),
            context_hash="0" * 64,
        )
        return replace(plan, jobs=(job,))

    submitted = store.execute(auth, cmd, submit, capability="submit")
    subject = C.ObjectRef.model_validate(submitted.result["submission"])
    before = store.read(auth, subject)
    leased = queue.claim_job("worker")
    claim = WorkerClaim.from_job(leased)
    result = gateway.run_job("v2.feedback", leased["payload"], claim=claim)
    # Crash after domain commit but before ACK: the same live claim reads the saved effect.
    again = gateway.run_job("v2.feedback", leased["payload"], claim=claim)
    assert again["replayed"] and calls == [1]
    queue.complete(leased["id"], leased["lease_token"], result)
    assert store.view(auth).state.status == "submitted"
    assert store.view(auth).state.business_seq == submitted.state.business_seq
    assert store.read(auth, subject) == before
    assert sum(x.ref.kind == "feedback" for x in store.view(auth).objects) == 1
    with pytest.raises(C.ProtocolError, match="session submitted"):
        store.execute(auth, command(store.view(auth), "bad-edit"), product_plan)
    with pytest.raises(C.ProtocolError, match="derived feedback only"):
        store.execute(
            auth,
            command(store.view(auth), "reopen-hack"),
            lambda *_: Mutation(state_changes={"status": "active"}),
            derived_subject=subject,
        )


def test_R03_R04_typed_restore_preserves_text_provenance_and_namespaces(foundation):
    store, auth, *_ = foundation
    file = C.FileRef(path="frozen-material.json", sha256=C.digest("public"))

    def resolver(actor, ref, as_of, bindings):
        bare = C.ObjectRef.model_validate(
            {k: v for k, v in ref.model_dump(mode="json").items() if k in C.ObjectRef.model_fields}
        )
        return C.ExternalReference(ref=bare, source=file, content_hash=file.sha256)

    store.register_reference_resolver("material", resolver)
    raw = {
        "id": "faq",
        "session_id": auth.session_id,
        "kind": "text",
        "content": "historical original",
    }
    legacy = C.LegacyProvenance(
        source_schema="browser-v1",
        source_session_id=auth.session_id,
        original_id="faq",
        original_kind="text",
        raw=raw,
        original_hash=C.digest(raw),
    )
    plan_payload = C.PlanPayload(
        sections={"id": "faq", "session_id": auth.session_id, "summary": "faq must remain literal"}
    )
    evidence = C.EvidenceRefV2(
        session_id=auth.session_id, kind="material", object_id="faq", version=1, observed_at_seq=0
    )

    def save(v, c, a):
        initial = product_plan(v, c, a, oid="faq")
        body = initial.writes[0].content | {
            "kind": "plan",
            "structured_payload": plan_payload.model_dump(mode="json"),
            "legacy": legacy.model_dump(mode="json"),
            "evidence_refs": [evidence.model_dump(mode="json")],
        }
        body["content_hash"] = C.digest(
            {"content": body["content"], "structured_payload": body["structured_payload"]}
        )
        return Mutation(
            writes=(
                initial.writes[0].model_copy(
                    update={"content": body, "dependencies": references(body)}
                ),
            )
        )

    parent = store.execute(auth, command(store.view(auth), "save"), save)
    service = SnapshotService(store)
    research = store.research_context(auth.session_id)
    snapshot = service.export(research, C.digest("source"))
    before = snapshot.snapshot_hash
    restored, token = service.restore(snapshot, session_id="typed-child")
    child_auth = store.authenticate(restored.session_id, token)
    child = store.read(
        child_auth,
        C.ObjectRef(
            session_id=restored.session_id,
            kind="product",
            object_id=restored.id_map[identity_key("product", "faq")],
            version=1,
        ),
    )
    assert child.content["structured_payload"] == plan_payload.model_dump(mode="json")
    assert child.content["legacy"] == legacy.model_dump(mode="json")
    assert child.content["evidence_refs"][0]["object_id"] == "faq"
    assert restored.id_map[identity_key("material", "faq")] == "faq"
    assert restored.id_map[identity_key("product", "faq")] != "faq"
    service.export(store.research_context(restored.session_id), C.digest("source"))
    assert service.export(research, C.digest("source")).snapshot_hash == before
    action = C.ActionProposal(
        id="edit",
        tool="work_products.versions.create",
        arguments=C.ProductEdit(
            kind="plan",
            product_id="faq",
            expected_head=1,
            structured_payload=plan_payload,
            legacy=legacy,
            evidence_refs=(evidence,),
        ).model_dump(mode="json"),
        purpose="typed remap",
    )
    mapped = SnapshotPortAdapter(store, C.digest("source")).remap_action(action, restored)
    assert mapped.arguments["product_id"] == restored.id_map[identity_key("product", "faq")]
    assert mapped.arguments["structured_payload"] == plan_payload.model_dump(mode="json")
    assert mapped.arguments["legacy"] == legacy.model_dump(mode="json")
    assert mapped.arguments["evidence_refs"][0]["object_id"] == "faq"
    assert mapped.arguments["evidence_refs"][0]["session_id"] == restored.session_id


def test_R05_public_disclosure_cannot_restore_private_quote():
    ref = C.EvidenceRefV2(
        session_id="s",
        kind="material",
        object_id="private",
        version=1,
        observed_at_seq=0,
        quote="SECRET-RAW-123",
        span_start=0,
        span_end=14,
    )
    fragment = C.SourceFragment(
        ref=ref,
        text="SECRET-RAW-123",
        channel="material",
        disclosure=C.DisclosurePolicy(
            mode="paraphrase_only", actors=("learner",), paraphrase="资源仍需核验"
        ),
    )
    safe = project_fragments((fragment,), "learner", 0)[0]
    reply = C.ObjectRef(session_id="s", kind="turn", object_id="reply", version=1)
    internal = C.DisclosureRecord(
        fact_id="fact",
        source=ref,
        reply_ref=reply,
        quote="资源仍需核验",
        verification="model_extracted",
        displayed_at_seq=0,
    )
    assert verify_disclosure_quotes("资源仍需核验", (internal,))
    seen = C.ObservedFragment(
        **safe.model_dump(exclude={"schema_version"}),
        audience="learner",
        acquired_via="role_reply",
        acquired_at_seq=0,
        disclosure_ref=reply,
    )
    args = dict(
        session_id="s",
        actor=C.Executor(id="human:s", kind="human"),
        as_of=C.VersionPoint(business_seq=0, workspace_revision=0, storage_revision=0),
        visible_sources=(seen,),
        next_seq=0,
    )
    with pytest.raises(ValidationError):
        C.Observation(**args, actual_disclosures=(internal.model_dump(mode="json"),))
    public = project_disclosures("资源仍需核验", (internal,), session_id="s", as_of_seq=0)
    obs = C.Observation(**args, actual_disclosures=public)
    assert (
        "SECRET-RAW-123" not in obs.model_dump_json()
        and "SECRET-RAW-123" in internal.model_dump_json()
    )
    with pytest.raises(C.ProtocolError):
        project_disclosures(
            "资源仍需核验",
            (
                internal.model_copy(
                    update={"reply_ref": reply.model_copy(update={"session_id": "foreign"})}
                ),
            ),
            session_id="s",
            as_of_seq=0,
        )


def test_R06_restore_replay_credentials_are_real_or_conflict(foundation):
    store, auth, *_ = foundation
    service = SnapshotService(store)
    snapshot = service.export(store.research_context(auth.session_id), C.digest("source"))
    first, token = service.restore(
        snapshot, session_id="restore-explicit", request_id="key", token="synthetic-first"
    )
    again, returned = service.restore(
        snapshot, session_id="restore-explicit", request_id="key", token=token
    )
    assert again.replayed and store.authenticate(again.session_id, returned)
    for supplied in ("different-synthetic-token", None):
        with pytest.raises(C.ProtocolError, match="restore token conflict"):
            service.restore(
                snapshot, session_id="restore-explicit", request_id="key", token=supplied
            )


def test_R08_invalid_provider_identity_keeps_received_evidence():
    raw = {
        "provider": "fixture",
        "text": "received body",
        "input_tokens": 123,
        "output_tokens": 7,
        "cost": 0.42,
    }
    calls = []

    def transport(*_):
        calls.append(1)
        return dict(raw)

    provider = C.SingleAttemptProvider(
        "fixture",
        "requested-model",
        C.ProviderCapabilities(seed_supported=False, decode_parameters=(), max_output_tokens=100),
        transport,
    )
    req = C.ProviderRequest(
        request_id="p",
        attempt_id="a",
        provider="fixture",
        model_revision="requested-model",
        prompt_revision="p1",
        messages=(),
        tools_digest=C.digest([]),
        deadline=datetime.now(timezone.utc) + timedelta(seconds=10),
        output_limit=100,
    )
    result = provider.call(req)
    assert calls == [1] and result.status == "invalid" and result.reply is None
    assert result.received.raw_response == raw and result.received.received_text == "received body"
    attempt = result.attempts[0]
    assert (attempt.input_tokens, attempt.output_tokens, attempt.cost) == (123, 7, 0.42)
    assert (
        attempt.usage_known
        and attempt.model_revision is None
        and attempt.expected_model_revision == "requested-model"
    )


def test_R09_G2_final_binds_the_single_successful_pass():
    decision = C.AnnotationDecision(
        task_type="relation", label="SUPPORTED", evidence_evaluable=True
    )
    passed = C.AnnotationPass(
        id="p",
        invocation_id="call",
        executor=C.Executor(id="model", kind="system"),
        status="success",
        input_hash="0" * 64,
        prompt_revision="p1",
        model_revision="m1",
        raw_output="synthetic output",
        decision=decision,
    )
    valid = dict(
        record_id="r",
        annotation_version="v2",
        input_hash="0" * 64,
        label_tier="G2",
        status="accepted",
        passes=(passed,),
        final=decision,
    )
    assert C.AnnotationV2(**valid)
    with pytest.raises(ValidationError):
        C.AnnotationV2(**(valid | {"final": decision.model_copy(update={"label": "CONTRADICTED"})}))
    second = passed.model_copy(update={"id": "second", "invocation_id": "second-call"})
    with pytest.raises(ValidationError):
        C.AnnotationV2(**(valid | {"passes": (passed, second)}))


def test_R07_read_only_request_query_recovers_pending_and_completed(foundation):
    store, auth, *_ = foundation
    registry = ExtensionRegistry()
    calls = []
    registry.register_job(
        "v2.product", lambda v, e, a: (calls.append(1), product_plan(v, e.command, a))[1]
    )
    gateway, queue, parent = queued_product(store, auth, registry)
    before = store.view(auth).state
    pending = gateway.request_result(auth, "q")
    assert (
        pending.status == "pending"
        and pending.jobs[0].origin_request_id == "q"
        and pending.jobs[0].effect_request_id == "q-effect"
    )
    assert calls == [] and store.view(auth).state == before
    for _ in range(3):
        assert gateway.request_result(auth, "q") == pending
    worker = Worker(
        queue,
        {
            "v2.product": ClaimedHandler(
                lambda payload, claim: gateway.run_job("v2.product", payload, claim=claim)
            )
        },
    )
    assert worker.run_once()
    completed = gateway.request_result(auth, "q")
    state = store.view(auth).state
    assert (
        completed.status == "completed"
        and completed.jobs[0].effect.boundary.request_id == "q-effect"
    )
    assert completed.response.boundary.request_id == "q"
    for _ in range(3):
        assert gateway.request_result(auth, "q") == completed
    assert calls == [1] and store.view(auth).state == state
    with pytest.raises(C.ProtocolError, match="request not found"):
        gateway.request_result(auth, "unknown")


def test_R07_identity_scope_expiry_and_revocation(foundation):
    store, owner, _, bindings, config = foundation
    registry = ExtensionRegistry()
    gateway = Gateway(store, registry)
    root_result = store.execute(owner, command(store.view(owner), "root-product"), product_plan)
    product = root_result.objects[0]
    now = datetime.now(timezone.utc)

    def grant(gid):
        value = C.DelegationGrant(
            id=gid,
            session_id=owner.session_id,
            actor_id="learner",
            executor=C.Executor(id="same-agent-label", kind="external_agent", delegation_id=gid),
            capabilities=("read", "act"),
            allowed_objects=(product.object_id,),
            allowed_actions=("save",),
            expires_at=now + timedelta(hours=1),
        )
        token = store.issue_delegation(owner, value)
        return store.authenticate(owner.session_id, token), token

    a, token_a = grant("a")
    b, _ = grant("b")
    cmd = command(store.view(a), "agent-edit")

    def edit(view, command, actor):
        original = view.get(product)
        body = original.content | {"version": 2, "executor": actor.executor.model_dump(mode="json")}
        return Mutation(
            writes=(
                ObjectWrite(
                    ref=product.model_copy(update={"version": 2}),
                    expected_head=1,
                    content=body,
                    dependencies=original.dependencies,
                ),
            )
        )

    store.execute(a, cmd, edit)
    assert gateway.request_result(a, "agent-edit").executor == a.executor
    with pytest.raises(C.ProtocolError):
        gateway.request_result(b, "agent-edit")
    other, token = store.create_session(bindings, config, {"capacity": 30})
    with pytest.raises(C.ProtocolError):
        gateway.request_result(store.authenticate(other.session_id, token), "agent-edit")
    # A narrower current scope must not return the saved arbitrary result payload.
    narrower = a.model_copy(update={"allowed_objects": ()})
    with store.db.transaction() as c:
        c.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == "a")
            .values(context=C.canonical(narrower))
        )
    with pytest.raises(C.ProtocolError):
        gateway.request_result(narrower, "agent-edit")
    expired = a.model_copy(update={"expires_at": now - timedelta(seconds=1)})
    with store.db.transaction() as c:
        c.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == "a")
            .values(context=C.canonical(expired))
        )
    with pytest.raises(C.ProtocolError, match="credential expired"):
        gateway.request_result(expired, "agent-edit")
    with store.db.transaction() as c:
        c.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == "a")
            .values(context=C.canonical(a), revoked=1)
        )
    with pytest.raises(C.ProtocolError, match="credential revoked"):
        gateway.request_result(a, "agent-edit")


def test_R07_public_route_exists_without_business_module_and_never_executes(tmp_path, foundation):
    _, _, _, bindings, config = foundation
    registry = ExtensionRegistry()
    registry.register_scenario("contract", ScenarioRegistration(bindings, config, {"capacity": 30}))
    app = create_app("sqlite:///" + str(tmp_path / "request-query.db"), extensions=registry)
    with TestClient(app) as client:
        created = client.post(
            "/sessions", json={"schema_version": 2, "scenario": "contract"}
        ).json()
        sid = created["session_id"]
        h = {"Authorization": "Bearer " + created["token"]}
        auth = app.state.v2_store.authenticate(sid, created["token"])
        app.state.v2_store.execute(
            auth, command(app.state.v2_store.view(auth), "lost-response"), product_plan
        )
        state = app.state.v2_store.view(auth).state
        response = client.get(f"/sessions/{sid}/requests/lost-response", headers=h)
        assert response.status_code == 200, response.text
        result = C.RequestResult.model_validate(response.json())
        assert (
            result.read_only
            and result.status == "completed"
            and result.request_id == "lost-response"
        )
        assert app.state.v2_store.view(auth).state == state
        assert client.get(f"/sessions/{sid}/requests/unknown", headers=h).status_code == 404
        assert client.get(f"/sessions/{sid}/requests/lost-response").status_code == 401
        assert "/sessions/{session_id}/requests/{request_id}" in app.openapi()["paths"]


def test_R02_real_worker_retries_failed_generation_then_saves_once(foundation):
    store, auth, *_ = foundation
    registry = ExtensionRegistry()
    queue = JobRepository(store.db)
    gateway = Gateway(store, registry)
    calls = []

    def feedback(view, envelope, actor):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("synthetic generation failure")
        subject = C.ObjectRef.model_validate(envelope.command.payload["subject"])
        obj = C.FeedbackV2(
            id="feedback-retried",
            session_id=actor.session_id,
            subject=subject,
            evaluation=view.bindings.evaluation,
            as_of=point(view.state),
            items=(),
            business_response="fixed subject result",
            next_options=(),
            verified_coverage=0,
            model_coverage=0,
        )
        return Mutation(
            writes=(
                ObjectWrite(
                    ref=C.ObjectRef(
                        session_id=actor.session_id, kind="feedback", object_id=obj.id, version=1
                    ),
                    expected_head=0,
                    content=obj.model_dump(mode="json"),
                    dependencies=(subject,),
                ),
            )
        )

    registry.register_job("v2.feedback", feedback)
    cmd = command(store.view(auth), "submit-retry", "submit").model_copy(
        update={"payload": C.SubmitInput(decision="no_go", products=()).model_dump(mode="json")}
    )

    def submit(view, command, actor):
        plan = record_submission(view, command, actor)
        return replace(
            plan,
            jobs=(
                JobRequest(
                    name="v2.feedback",
                    command=command.model_copy(
                        update={
                            "request_id": "retry-effect",
                            "operation": "feedback.create",
                            "payload": {"subject": plan.result["submission"]},
                        }
                    ),
                    context_hash="0" * 64,
                ),
            ),
        )

    submitted = store.execute(auth, cmd, submit, capability="submit")
    sid = submitted.result["submission"]
    before = store.read(auth, C.ObjectRef.model_validate(sid))
    worker = Worker(
        queue,
        {
            "v2.feedback": ClaimedHandler(
                lambda payload, claim: gateway.run_job("v2.feedback", payload, claim=claim)
            )
        },
    )
    assert worker.run_once()
    assert gateway.request_result(auth, "submit-retry").status == "pending"
    assert not any(x.ref.kind == "feedback" for x in store.view(auth).objects)
    assert worker.run_once()
    recovered = gateway.request_result(auth, "submit-retry")
    assert recovered.status == "completed" and recovered.jobs[0].effect_request_id == "retry-effect"
    assert len(calls) == 2 and store.view(auth).state.status == "submitted"
    assert store.read(auth, C.ObjectRef.model_validate(sid)) == before
    assert sum(x.ref.kind == "feedback" for x in store.view(auth).objects) == 1
