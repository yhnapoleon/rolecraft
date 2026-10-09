"""Actual common Gateway/worker/private port with controlled non-network models."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import replace
import hashlib, json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from career_lab.contracts import v2 as C
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry, Gateway, JobEnvelope
from career_lab.api.private_roles import (
    install_private_role_runtime,
    PrivateRoleGenerationPort,
    RuleReplyVerifier,
)
from career_lab.api.role_snapshot import FixedRoleSnapshotPort
from career_lab.runtime.context_v2 import ContextPort
from career_lab.runtime.roles_v2 import RoleService
from career_lab.runtime.model_adapter import ModelReply
from career_lab.storage.v2_store import V2Store, Mutation
from career_lab.storage.v2_tables import v2_objects, v2_transactions
from career_lab.storage.v2_snapshot import SnapshotService
from career_lab.jobs.repository import JobRepository, jobs
from career_lab.jobs.worker import Worker, ClaimedHandler, WorkerClaim
from .conftest import command, product_plan
from .test_core_wiring_role_snapshot import environment


class ControlledModel:
    revision = "controlled-role-port"

    def __init__(self, mode="success", hook=None):
        self.calls = []
        self.mode = mode
        self.hook = hook

    def complete(self, messages, tools):
        self.calls.append(messages)
        if self.hook:
            self.hook()
        if self.mode == "timeout":
            raise TimeoutError("controlled")
        if self.mode == "dump":
            return ModelReply(text=messages[0]["content"])
        if messages[0]["content"].startswith("Review the actual reply"):
            return ModelReply(
                text=json.dumps(
                    {
                        "request_kinds": ["business_judgment"],
                        "facts_answered": True,
                        "citations_supported": True,
                        "within_knowledge": True,
                        "preserves_stance": True,
                        "no_complete_solution": True,
                        "no_resource_approval": True,
                        "one_main_question": True,
                        "conditions_preserved": True,
                        "language_match": True,
                        "decision": "supported",
                    }
                )
            )
        return ModelReply(
            text="已收到。我会继续核对依据。", usage={"prompt_tokens": 11, "completion_tokens": 7}
        )


@pytest.fixture
def role_api(foundation, tmp_path):
    env = environment(foundation)
    store, owner, token, catalog, _, _ = env
    model = ControlledModel()
    registry = ExtensionRegistry()
    files = {}
    for version in (1, 2):
        p = tmp_path / f"policy-{version}.txt"
        p.write_text(f"POLICY_VERSION_{version}")
        files[version] = C.FileRef(path=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    calls = []

    def resolver(auth, ref, at, bindings, *, scenario_state):
        calls.append((auth.actor_id, ref.object_id, ref.version))
        if (
            auth.actor_id not in {"learner", "tech_lead", "business_lead"}
            or ref.object_id != "policy"
            or scenario_state.material_activation.get("policy:" + str(ref.version)) is None
        ):
            raise C.ProtocolError("material_unavailable", status=404)
        f = files[ref.version]
        C.read_file(tmp_path, f)
        bare = C.ObjectRef.model_validate(
            {k: v for k, v in ref.model_dump(mode="json").items() if k in C.ObjectRef.model_fields}
        )
        return C.ExternalReference(ref=bare, source=f, content_hash=f.sha256)

    registry.register_reference_resolver("material", resolver, contextual=True)
    install_private_role_runtime(registry, catalog, model, enable_generation=True)
    app = create_app(str(store.db.engine.url), extensions=registry)
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer " + token
    worker_store = V2Store(str(store.db.engine.url))
    gateway = Gateway(worker_store, registry)
    repository = JobRepository(worker_store.db)
    worker = Worker(
        repository,
        {
            "v2.role_turn": ClaimedHandler(
                lambda payload, claim: gateway.run_job("v2.role_turn", payload, claim=claim),
                retry_on_error=registry.job_handlers["v2.role_turn"].retry_on_error,
            )
        },
    )
    yield dict(
        app=app,
        client=client,
        store=app.state.v2_store,
        owner=owner,
        token=token,
        catalog=catalog,
        model=model,
        registry=registry,
        worker_store=worker_store,
        gateway=gateway,
        jobs=repository,
        worker=worker,
        resolver_calls=calls,
    )
    client.close()
    app.state.store.close()
    worker_store.db.engine.dispose()


def queue(api, key="question", *, client=None, auth=None, shares=()):
    store = api["store"]
    auth = auth or api["owner"]
    body = C.TurnInput(role_id="tech_lead", text="请核对当前依据。", shares=shares)
    cmd = command(store.view(auth), key, "turns.create").model_copy(
        update={"payload": body.model_dump(mode="json")}
    )
    response = (client or api["client"]).post(
        f"/sessions/{auth.session_id}/turns", json=cmd.model_dump(mode="json")
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["queued_jobs"][0], cmd


def private_records(api):
    return [
        row
        for row in api["store"].view(api["store"].research_context(api["owner"].session_id)).objects
        if row.ref.kind == "role_context"
    ]


def test_real_private_port_commits_reply_and_audit_without_public_recovery(role_api):
    api = role_api
    jid, cmd = queue(api)
    before = api["store"].view(api["owner"]).state
    assert api["worker"].run_once()
    job = api["jobs"].get(jid)
    assert job["status"] == "completed", job["error"]
    assert len(api["model"].calls) == 1
    records = private_records(api)
    assert len(records) == 2
    phases = {r.content["generation_audit"]["phase"]: r for r in records}
    assert set(phases) == {"attempt", "completed"}
    for record in records:
        assert set(record.visible_to) == {"system", "tech_lead"}
        audit = record.content["generation_audit"]
        assert (
            audit["scope"]["executor"] == api["owner"].executor.model_dump(mode="json")
            and audit["worker_id"]
            and audit["lease_token_hash"]
        )
        assert (
            audit["attempts"][0]["input_tokens"] == 11
            and audit["attempts"][0]["output_tokens"] == 7
        )
        with pytest.raises(C.ProtocolError):
            api["store"].read(api["owner"], record.ref)
    view = api["store"].view(api["owner"])
    assert not any(r.ref.kind == "role_context" for r in view.objects)
    assert (
        view.state.business_seq == before.business_seq
        and view.state.workspace_revision == before.workspace_revision + 1
    )
    response = api["client"].get(f"/sessions/{api['owner'].session_id}/requests/{cmd.request_id}")
    assert response.status_code == 200, response.text
    assert (
        "generation_audit" not in response.text
        and "prompt_messages" not in response.text
        and "POLICY_VERSION_1" not in response.text
    )
    assert "已收到" in response.text
    for record in records:
        assert record.ref.object_id not in response.text
    assert (
        api["client"]
        .post(f"/sessions/{api['owner'].session_id}/turns", json=cmd.model_dump(mode="json"))
        .json()["replayed"]
    )
    assert len(api["model"].calls) == 1


def test_scoped_agent_uses_original_executor_without_private_scope_expansion(role_api):
    api = role_api
    owner = api["owner"]
    grant = C.DelegationGrant(
        id="agent-ask",
        session_id=owner.session_id,
        actor_id="learner",
        executor=C.Executor(id="agent", kind="external_agent", delegation_id="agent-ask"),
        capabilities=("read", "act"),
        allowed_actions=("turns.create",),
        allowed_objects=(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    token = api["store"].issue_delegation(owner, grant)
    auth = api["store"].authenticate(owner.session_id, token)
    client = TestClient(api["app"])
    client.headers["Authorization"] = "Bearer " + token
    try:
        jid, cmd = queue(api, client=client, auth=auth)
        api["worker"].run_once()
        job = api["jobs"].get(jid)
        assert job["status"] == "completed", job["error"]
        current = api["store"].authenticate(owner.session_id, token)
        assert current.allowed_objects == ()
        visible = api["store"].view(current).objects
        assert {r.ref.kind for r in visible} == {"role_turn", "role_reply"}
        reply = next(r for r in visible if r.ref.kind == "role_reply")
        assert reply.creator == auth.executor and reply.content[
            "executor"
        ] == auth.executor.model_dump(mode="json")
        for record in private_records(api):
            assert record.content["generation_audit"]["scope"][
                "executor"
            ] == auth.executor.model_dump(mode="json")
            with pytest.raises(C.ProtocolError):
                api["store"].read(current, record.ref)
        response = client.get(f"/sessions/{auth.session_id}/requests/{cmd.request_id}")
        assert response.status_code == 200, response.text
        assert "prompt_messages" not in response.text and "POLICY_VERSION_1" not in response.text
    finally:
        client.close()


@pytest.mark.parametrize("mode", ["timeout", "dump"])
def test_failed_invocations_are_private_and_retained_without_public_reply(role_api, mode):
    api = role_api
    api["model"].mode = mode
    jid, cmd = queue(api)
    api["worker"].run_once()
    row = api["jobs"].get(jid)
    assert row["status"] == "failed"
    assert not api["worker"].run_once()
    turn = next(r for r in api["store"].view(api["owner"]).objects if r.ref.kind == "role_turn")
    assert turn.content["input"]["text"] == "请核对当前依据。"
    records = private_records(api)
    assert len(records) == 1 and records[0].content["generation_audit"]["phase"] == "attempt"
    assert records[0].content["generation_audit"]["attempts"][0]["status"] == (
        "timeout" if mode == "timeout" else "failed"
    )
    assert not any(r.ref.kind == "role_reply" for r in api["store"].view(api["owner"]).objects)
    assert len(api["model"].calls) == 1


def test_actual_claim_loss_before_generation_calls_no_model(role_api):
    api = role_api
    jid, _ = queue(api)
    job = api["jobs"].claim_job("controlled-worker")
    claim = WorkerClaim.from_job(job)
    with api["worker_store"].db.transaction() as conn:
        conn.execute(update(jobs).where(jobs.c.id == jid).values(lease_token="different-lease"))
    with pytest.raises(C.ProtocolError, match="worker lease lost"):
        api["gateway"].run_job("v2.role_turn", job["payload"], claim=claim)
    assert api["model"].calls == [] and private_records(api) == []


def test_default_factory_keeps_generation_closed(role_api):
    api = role_api
    registry = ExtensionRegistry()
    install_private_role_runtime(registry, api["catalog"], api["model"])
    # No model invocation even if a valid queued job is supplied to this closed factory.
    jid, _ = queue(api)
    job = api["jobs"].claim_job("closed")
    gateway = Gateway(api["worker_store"], registry)
    with pytest.raises(C.ProtocolError, match="role integration not accepted"):
        gateway.run_job("v2.role_turn", job["payload"], claim=WorkerClaim.from_job(job))
    assert api["model"].calls == []


@pytest.mark.parametrize("failure", ["missing", "learner_audience", "system_only"])
def test_real_worker_rejects_missing_or_wrong_private_audience(role_api, monkeypatch, failure):
    api = role_api
    original = PrivateRoleGenerationPort.prepare

    def altered(self, *args, **kwargs):
        writes = original(self, *args, **kwargs)
        if failure == "missing":
            return ()
        return (
            writes[0].model_copy(
                update={
                    "visible_to": ("learner",) if failure == "learner_audience" else ("system",)
                }
            ),
        )

    monkeypatch.setattr(PrivateRoleGenerationPort, "prepare", altered)
    jid, _ = queue(api)
    api["worker"].run_once()
    row = api["jobs"].get(jid)
    assert row["status"] == "failed" and row["error"] in {
        "role_private_audit_incomplete",
        "role_private_audit_invalid",
    }
    assert len(api["model"].calls) == 1
    records = private_records(api)
    assert len(records) == 1 and records[0].content["generation_audit"]["phase"] == "attempt"
    assert not any(r.ref.kind == "role_reply" for r in api["store"].view(api["owner"]).objects)


def test_reply_and_completed_audit_rollback_together_but_real_attempt_remains(
    role_api, monkeypatch
):
    api = role_api
    original = api["worker_store"].execute
    fail = [True]

    def execute(*args, **kwargs):
        if kwargs.get("job_context") is not None and fail[0]:
            fail[0] = False

            def fault(stage):
                if stage == "after_objects":
                    raise RuntimeError("controlled commit rollback")

            kwargs["fault"] = fault
        return original(*args, **kwargs)

    monkeypatch.setattr(api["worker_store"], "execute", execute)
    jid, _ = queue(api)
    api["worker"].run_once()
    assert api["jobs"].get(jid)["status"] == "failed"
    assert len(private_records(api)) == 1 and not any(
        r.ref.kind == "role_reply" for r in api["store"].view(api["owner"]).objects
    )
    assert not api["worker"].run_once()
    assert len(api["model"].calls) == 1
    store = api["store"]
    owner = api["owner"]
    refresh = command(store.view(owner), "explicit-retry", "jobs.refresh").model_copy(
        update={"payload": {"job_id": jid}}
    )
    store.refresh_job(owner, refresh, jid)
    api["worker"].run_once()
    assert api["jobs"].get(jid)["status"] == "completed"
    records = private_records(api)
    assert sum(r.content["generation_audit"]["phase"] == "attempt" for r in records) == 2
    assert sum(r.content["generation_audit"]["phase"] == "completed" for r in records) == 1
    assert len(api["model"].calls) == 2


def test_pause_during_invocation_keeps_audit_and_original_question_then_explicit_refresh(role_api):
    api = role_api
    store = api["store"]
    owner = api["owner"]

    def pause():
        api["model"].hook = None
        store.execute(
            owner,
            command(store.view(owner), "pause-during", "pause"),
            lambda *_: Mutation(state_changes={"status": "paused"}),
        )

    api["model"].hook = pause
    jid, original = queue(api)
    api["worker"].run_once()
    row = api["jobs"].get(jid)
    assert row["status"] == "needs_context" and row["error"] == "job_session_inactive"
    assert len(private_records(api)) == 1 and not any(
        r.ref.kind == "role_reply" for r in store.view(owner).objects
    )
    turn = next(r for r in store.view(owner).objects if r.ref.kind == "role_turn")
    assert turn.content["input"]["text"] == "请核对当前依据。"
    store.execute(
        owner,
        command(store.view(owner), "resume-after", "resume"),
        lambda *_: Mutation(state_changes={"status": "active"}),
    )
    refresh = command(store.view(owner), "refresh", "jobs.refresh").model_copy(
        update={"payload": {"job_id": jid}}
    )
    store.refresh_job(owner, refresh, jid)
    api["worker"].run_once()
    assert api["jobs"].get(jid)["status"] == "completed"
    completed = next(
        r for r in private_records(api) if r.content["generation_audit"]["phase"] == "completed"
    )
    assert completed.content["generation_audit"]["refresh_count"] == 1 and completed.content[
        "generation_audit"
    ]["request"] == turn.ref.model_dump(mode="json")
    assert len(api["model"].calls) == 2


def test_revocation_during_model_call_keeps_only_system_audit(role_api):
    api = role_api
    store = api["store"]
    owner = api["owner"]
    grant = C.DelegationGrant(
        id="revoke-during",
        session_id=owner.session_id,
        actor_id="learner",
        executor=C.Executor(id="agent", kind="external_agent", delegation_id="revoke-during"),
        capabilities=("read", "act"),
        allowed_actions=("turns.create",),
        allowed_objects=(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    token = store.issue_delegation(owner, grant)
    auth = store.authenticate(owner.session_id, token)
    client = TestClient(api["app"])
    client.headers["Authorization"] = "Bearer " + token
    api["model"].hook = lambda: store.revoke_delegation(owner, grant.id)
    try:
        jid, _ = queue(api, client=client, auth=auth)
        api["worker"].run_once()
        row = api["jobs"].get(jid)
        assert row["status"] == "failed" and row["error"] == "credential_revoked_or_invalid"
        records = private_records(api)
        assert len(records) == 1 and records[0].creator.kind == "system"
        assert records[0].content["generation_audit"]["scope"][
            "executor"
        ] == auth.executor.model_dump(mode="json")
        assert not any(r.ref.kind == "role_reply" for r in store.view(owner).objects)
    finally:
        client.close()


def test_three_rounds_use_persisted_private_history_across_api_worker_instances(role_api):
    api = role_api
    store = api["store"]
    for n in range(3):
        jid, _ = queue(api, "round-" + str(n))
        api["worker"].run_once()
        assert api["jobs"].get(jid)["status"] == "completed"
    generation_calls = [call for call in api["model"].calls if "\nCONTEXT\n" in call[0]["content"]]
    review_calls = [
        call
        for call in api["model"].calls
        if call[0]["content"].startswith("Review the actual reply")
    ]
    assert len(generation_calls) == 3
    assert len(review_calls) == 2
    assert len(api["model"].calls) == 5
    assert "已收到。我会继续核对依据。" in generation_calls[1][0]["content"]
    assert "已收到。我会继续核对依据。" in generation_calls[2][0]["content"]
    records = private_records(api)
    assert len(records) == 8
    assert len([r for r in store.view(api["owner"]).objects if r.ref.kind == "role_reply"]) == 3
    assert not any(r.ref.kind == "role_display" for r in store.view(api["owner"]).objects)


def test_private_plan_tampering_after_authorization_and_bare_audit_are_rejected(role_api):
    api = role_api
    jid, _ = queue(api)
    job = api["jobs"].claim_job("manual")
    claim = WorkerClaim.from_job(job)
    envelope = JobEnvelope.model_validate(job["payload"])
    store = api["worker_store"]
    auth = store.guard_job(envelope.context)
    view = store.job_view(auth, envelope.context, command=envelope.command, worker_claim=claim)
    port = PrivateRoleGenerationPort(store, api["catalog"], view, envelope, auth)
    service = RoleService(
        ContextPort(api["catalog"], FixedRoleSnapshotPort(store, api["catalog"])),
        api["model"],
        private_port=port,
        reply_verifier=RuleReplyVerifier(),
    )
    plan = port.authorize(service.generate(view, envelope, auth))
    private = next(w for w in plan.writes if w.ref.kind == "role_context")
    changed = replace(plan, result=plan.result | {"injected": "unapproved"})
    with pytest.raises(C.ProtocolError, match="role authority invalid"):
        store.execute(
            auth,
            envelope.command,
            lambda *_: changed,
            worker_fence=claim,
            job_context=envelope.context,
        )
    with pytest.raises(C.ProtocolError, match="role private authority required"):
        store.execute(
            auth, command(store.view(auth), "bare-audit"), lambda *_: Mutation(writes=(private,))
        )
    assert not any(r.ref.kind == "role_reply" for r in store.view(auth).objects)


def test_actual_event_reference_and_attachment_history_survive_private_commit_and_snapshot(
    role_api,
):
    from career_lab.storage.v2_store import ObjectWrite, EventDraft
    from career_lab.storage.v2_lifecycle import point

    api = role_api
    store = api["store"]
    owner = api["owner"]
    product = store.execute(owner, command(store.view(owner), "attachment"), product_plan).objects[
        0
    ]
    share = C.ProductShare(
        id="attachment-share",
        session_id=owner.session_id,
        version=1,
        product=product,
        recipient_role="tech_lead",
        shared_at=point(store.view(owner).state),
    )
    share_ref = C.ObjectRef(
        session_id=owner.session_id, kind="share", object_id=share.id, version=1
    )
    store.execute(
        owner,
        command(store.view(owner), "share-attachment"),
        lambda *_: Mutation(
            writes=(
                ObjectWrite(
                    ref=share_ref,
                    expected_head=0,
                    content=share.model_dump(mode="json"),
                    dependencies=(product,),
                ),
            )
        ),
    )
    jid, _ = queue(api, "attached-question", shares=(share_ref,))
    api["worker"].run_once()
    assert api["jobs"].get(jid)["status"] == "completed"
    store.execute(
        owner,
        command(store.view(owner), "role-notice"),
        lambda *_: Mutation(
            events=(
                EventDraft(
                    type="policy_updated",
                    visible_to=("tech_lead",),
                    refs=(product,),
                    data={"private_notice": "DO_NOT_EXPORT_THIS_NOTICE"},
                ),
            )
        ),
    )
    jid, _ = queue(api, "later-question")
    api["worker"].run_once()
    row = api["jobs"].get(jid)
    assert row["status"] == "completed", row["error"]
    generation_calls = [call for call in api["model"].calls if "\nCONTEXT\n" in call[0]["content"]]
    review_calls = [
        call
        for call in api["model"].calls
        if call[0]["content"].startswith("Review the actual reply")
    ]
    assert len(generation_calls) == 2
    assert len(review_calls) == 2
    assert len(api["model"].calls) == 4
    assert "draft with an uncertain claim" in generation_calls[-1][0]["content"]
    audits = private_records(api)
    latest = max(
        (r for r in audits if r.content["generation_audit"]["phase"] == "completed"),
        key=lambda r: r.created_storage_revision,
    )
    assert len(latest.content["known_events"]) == 1
    assert "DO_NOT_EXPORT_THIS_NOTICE" not in C.canonical(latest.content)
    event = C.ObjectRef.model_validate(latest.content["known_events"][0])
    with pytest.raises(C.ProtocolError):
        store.can_reference(owner, event)
    research = store.research_context(owner.session_id)
    snapshot = SnapshotService(store).export(research, C.digest("controlled source"))
    fork = V2Store(str(store.db.engine.url))
    Gateway(fork, api["registry"])
    restored, token = SnapshotService(fork).restore(snapshot, session_id="fork-role-snapshot")
    exported = SnapshotService(fork).export(
        fork.research_context(restored.session_id), C.digest("controlled source")
    )
    event_ids = {e.id for e in exported.events}
    for record in exported.objects:
        for ref in record.dependencies:
            if ref.kind == "event":
                assert ref.object_id in event_ids and ref.session_id == restored.session_id
    fork.db.engine.dispose()


@pytest.mark.parametrize("field", ["generation_audit", "scope", "used_sources", "job_attempt"])
def test_historical_new_audit_fields_remain_private_and_unchanged(role_api, field):
    from sqlalchemy import insert
    from career_lab.storage.v2_tables import v2_heads

    api = role_api
    store = api["store"]
    owner = api["owner"]
    ref = C.ObjectRef(
        session_id=owner.session_id, kind="role_reply", object_id="old-" + field, version=1
    )
    content = {
        "id": ref.object_id,
        "session_id": owner.session_id,
        "role_id": "tech_lead",
        "version": 1,
        field: {"private": "PRIVATE_AUDIT_MARKER"},
    }
    record = C.StoredObject(
        ref=ref, content=content, visible_to=("learner", "tech_lead"), created_storage_revision=0
    )
    with store.db.transaction() as conn:
        conn.execute(
            insert(v2_objects).values(
                session_id=owner.session_id,
                kind=ref.kind,
                id=ref.object_id,
                version=1,
                record=C.canonical(record),
                created_revision=0,
            )
        )
        conn.execute(
            insert(v2_heads).values(
                session_id=owner.session_id, kind=ref.kind, id=ref.object_id, version=1
            )
        )
    with pytest.raises(C.ProtocolError):
        store.read(owner, ref)
    assert not any(r.ref == ref for r in store.view(owner).objects)
    actual = store.read(store.research_context(owner.session_id), ref)
    assert actual == record and "PRIVATE_AUDIT_MARKER" in actual.model_dump_json()


def test_production_claim_survives_store_reconstruction_and_configuration_change(role_api):
    api = role_api
    jid, _ = queue(api)
    job = api["jobs"].claim_job("original-worker")
    claim = WorkerClaim.from_job(job)
    envelope = JobEnvelope.model_validate(job["payload"])

    def port_for(store, claim):
        auth = store.guard_job(envelope.context)
        view = store.job_view(auth, envelope.context, command=envelope.command, worker_claim=claim)
        return PrivateRoleGenerationPort(store, api["catalog"], view, envelope, auth), auth

    first, auth = port_for(api["worker_store"], claim)
    assert first.claim_model_call(envelope, auth, "role_reply", "provider-a") is True
    # A fresh store and a changed actual worker lease still share the same claim.
    with api["store"].db.transaction() as conn:
        conn.execute(
            update(jobs)
            .where(jobs.c.id == jid)
            .values(worker_id="replacement-worker", lease_token="replacement-lease", attempt=2)
        )
    replacement_claim = WorkerClaim(jid, "replacement-lease", "replacement-worker", 2)
    rebuilt = V2Store(str(api["store"].db.engine.url))
    Gateway(rebuilt, api["registry"])
    try:
        second, current = port_for(rebuilt, replacement_claim)
        assert second.claim_model_call(envelope, current, "role_reply", "provider-b") is False
        assert second.claim_model_call(envelope, current, "role_reply_review", "mechanical") is True
        assert (
            second.claim_model_call(envelope, current, "role_reply_review", "different-config")
            is False
        )
        assert not api["model"].calls
    finally:
        rebuilt.db.engine.dispose()


@pytest.mark.parametrize(
    "language,text,expected",
    [
        ("zh", "我会继续核对依据。", "consistent"),
        ("en", "I will check the available evidence.", "consistent"),
        ("en", "我会继续核对依据。", "undetermined"),
        ("zh", "Please check the evidence.", "undetermined"),
        ("en", "123 --", "undetermined"),
    ],
)
def test_mechanical_reply_verifier_is_bound_and_never_claims_semantics(
    role_api, language, text, expected
):
    from career_lab.storage.role_memory import RoleTurn, stance_digest

    api = role_api
    jid, _ = queue(api)
    job = api["jobs"].claim_job("review-worker")
    envelope = JobEnvelope.model_validate(job["payload"])
    store = api["worker_store"]
    auth = store.guard_job(envelope.context)
    view = store.job_view(
        auth, envelope.context, command=envelope.command, worker_claim=WorkerClaim.from_job(job)
    )
    port = PrivateRoleGenerationPort(store, api["catalog"], view, envelope, auth)
    port.require_available()
    snapshot = replace(port.snapshot, work_language=language)
    request = RoleTurn.model_validate(
        view.get(C.ObjectRef.model_validate(envelope.command.payload["subject"])).content
    )
    claims = []

    def no_model_attempt(*args):
        raise AssertionError("mechanical check must not report a provider invocation")

    review = RuleReplyVerifier().check(
        snapshot,
        auth,
        request,
        text,
        record_attempt=no_model_attempt,
        begin_call=lambda *args: claims.append(args),
    )
    assert claims == [("role_reply_review", RuleReplyVerifier.revision)]
    assert (
        review.decision == expected
        and review.semantic_quality == "unverified"
        and review.learner_penalty_allowed is False
    )
    assert review.state_hash == stance_digest(
        snapshot.stance_state
    ) and review.reply_hash == C.digest(text)
    assert review.checked_at == snapshot.context.as_of
    assert (
        review.review_ref.sha256
        == hashlib.sha256(
            (Path(__file__).resolve().parents[3] / review.review_ref.path).read_bytes()
        ).hexdigest()
    )
    assert not api["model"].calls
