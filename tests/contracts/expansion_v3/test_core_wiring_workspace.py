"""Fixed W03 plans through public Gateway; synthetic session, not full product QA."""

from datetime import datetime, timedelta, timezone
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, inspect, update
from career_lab.contracts import v2 as C
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry, Gateway
from career_lab.api.workspace_integration import install_workspace_recovery, apply_import
from career_lab.workspace.extension import install_workspace_operations
from career_lab.storage.v2_store import Mutation, ObjectWrite, JobRequest, references
from career_lab.storage.v2_tables import v2_objects, v2_transactions, v2_events
from career_lab.jobs.repository import JobRepository
from career_lab.jobs.worker import Worker, ClaimedHandler
from .conftest import command, product_plan

ROLES = ("tech_lead", "business_lead")


@pytest.fixture
def workspace_api(foundation):
    store, auth, token, *_ = foundation
    registry = ExtensionRegistry()
    install_workspace_operations(registry, roles=ROLES)
    install_workspace_recovery(registry, roles=ROLES)
    app = create_app(str(store.db.engine.url), extensions=registry)
    with TestClient(app) as c:
        yield app, c, app.state.v2_store, auth, {"Authorization": "Bearer " + token}
    app.state.store.close()


def send(api, path, key, operation, payload, method="POST", headers=None):
    app, c, store, auth, h = api
    s = store.view(auth).state
    body = {
        "schema_version": 2,
        "request_id": key,
        "operation": operation,
        "expected_version": s.business_seq,
        "expected_workspace_revision": s.workspace_revision,
        "payload": payload,
    }
    return c.request(
        method, f"/sessions/{auth.session_id}" + path, headers=headers or h, json=body
    ), body


def payload():
    raws = [
        {"id": "old-task", "kind": "task", "title": "Original task", "note": "Original task note"},
        {
            "id": "old-work",
            "kind": "text",
            "taskId": "old-task",
            "title": "Current title",
            "body": "current body",
            "revision": 3,
            "sourceHistory": [
                {"revision": 1, "title": "Earlier title", "kind": "text", "body": "earlier body"}
            ],
            "archive_ref": {
                "session_id": "old-session",
                "kind": "test",
                "object_id": "old-test",
                "version": 1,
                "observed_at_seq": 999,
            },
        },
    ]
    items = tuple(
        C.LegacyProvenance(
            source_schema="browser-v1",
            source_session_id="old-session",
            original_id=r["id"],
            original_kind=r["kind"],
            raw=r,
            original_hash=C.digest(r),
        )
        for r in raws
    )
    return C.WorkspaceImport(
        package_id="local-package",
        mode="preview",
        source_schema="browser-v1",
        source_session_id="old-session",
        items=items,
        package_hash=C.digest([x.model_dump(mode="json") for x in items]),
    ).model_dump(mode="json")


def counts(store):
    with store.db.engine.connect() as c:
        return tuple(
            c.execute(select(func.count()).select_from(t)).scalar_one()
            for t in (v2_objects, v2_transactions, v2_events)
        )


def test_preview_is_read_only_then_atomic_import_keeps_history_and_task_sources(workspace_api):
    api = workspace_api
    app, c, store, auth, h = api
    body = payload()
    before = store.view(auth).state
    before_counts = counts(store)
    for index in range(2):
        response, _ = send(api, "/workspace-imports", f"preview-{index}", "workspace_imports", body)
        assert response.status_code == 200, response.text
        preview = response.json()["result"]
        assert (
            preview["as_of"]["storage_revision"] == before.storage_revision
            and not preview["applied"]
        )
    assert store.view(auth).state == before and counts(store) == before_counts
    apply = {
        **body,
        "mode": "apply",
        "preview_storage_revision": preview["as_of"]["storage_revision"],
    }
    response, command_body = send(api, "/workspace-imports", "apply", "workspace_imports", apply)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["boundary"]["start_seq"] == result["boundary"]["end_seq"] == before.business_seq
    assert result["result"]["as_of"]["storage_revision"] == result["state"]["storage_revision"]
    records = store.view(auth).objects
    products = [x for x in records if x.ref.kind == "product"]
    assert [x.ref.version for x in products] == [1, 2]
    assert {x.content["content"] for x in products} == {"earlier body", "current body"}
    assert products[-1].content["legacy"]["raw"] == body["items"][1]["raw"]
    receipt = next(x for x in records if x.ref.kind == "workspace_import")
    typed = C.WorkspaceImportReceipt.model_validate(receipt.content)
    assert typed.task_sources[0].source.raw == body["items"][0]["raw"]
    assert any(
        x.reason == "missing_history" and x.original_version == 2 for x in typed.result.conflicts
    )
    assert not any(x.ref.kind == "legacy_task" for x in records)
    assert not any(name.startswith("w03_") for name in inspect(store.db.engine).get_table_names())
    committed = counts(store)
    replay = c.post(f"/sessions/{auth.session_id}/workspace-imports", headers=h, json=command_body)
    assert replay.status_code == 200 and replay.json()["replayed"]
    recovered = c.get(f"/sessions/{auth.session_id}/requests/apply", headers=h)
    assert (
        recovered.status_code == 200 and recovered.json()["response"]["result"] == result["result"]
    )
    listing = c.get(
        f"/sessions/{auth.session_id}/workspace-imports/{receipt.ref.object_id}", headers=h
    )
    assert listing.status_code == 200, listing.text
    assert (
        listing.json()["result"]["result"]["items"][0]["fingerprint"] == typed.fingerprint
        and counts(store) == committed
    )


def test_stale_preview_and_same_package_different_content_are_rejected(workspace_api):
    api = workspace_api
    _, c, store, auth, h = api
    body = payload()
    preview, _ = send(api, "/workspace-imports", "preview", "workspace_imports", body)
    assert preview.status_code == 200
    assert (
        send(api, "/work-items", "other", "work_items.create", {"title": "concurrent work"})[
            0
        ].status_code
        == 200
    )
    response, _ = send(
        api,
        "/workspace-imports",
        "stale",
        "workspace_imports",
        {
            **body,
            "mode": "apply",
            "preview_storage_revision": preview.json()["result"]["as_of"]["storage_revision"],
        },
    )
    assert response.status_code == 409 and response.json()["code"] == "import_preview_stale"
    current, _ = send(api, "/workspace-imports", "fresh-preview", "workspace_imports", body)
    assert (
        send(
            api,
            "/workspace-imports",
            "apply",
            "workspace_imports",
            {
                **body,
                "mode": "apply",
                "preview_storage_revision": current.json()["result"]["as_of"]["storage_revision"],
            },
        )[0].status_code
        == 200
    )
    body["items"][1]["raw"]["body"] = "different"
    body["items"][1]["original_hash"] = C.digest(body["items"][1]["raw"])
    body["package_hash"] = C.digest(body["items"])
    conflict, _ = send(api, "/workspace-imports", "different-preview", "workspace_imports", body)
    assert conflict.status_code == 409 and conflict.json()["code"] == "import_package_conflict"


def test_import_failure_rolls_back_every_version_and_receipt(workspace_api):
    _, _, store, auth, _ = workspace_api
    p = payload()
    p.update(mode="apply", preview_storage_revision=store.view(auth).state.storage_revision)
    cmd = command(store.view(auth), "rollback", "workspace_imports").model_copy(
        update={"payload": p}
    )
    before = counts(store)

    def fault(stage):
        if stage == "after_objects":
            raise RuntimeError("injected rollback")

    with pytest.raises(RuntimeError):
        store.execute(
            auth,
            cmd,
            lambda v, c, a: apply_import(
                v, c, a, roles=ROLES, clock=lambda: datetime.now(timezone.utc)
            ),
            fault=fault,
        )
    assert counts(store) == before and not any(
        x.ref.kind in {"product", "workspace_import"} for x in store.view(auth).objects
    )


def make_product_and_shares(api):
    product, _ = send(
        api,
        "/work-products",
        "product",
        "work_products.create",
        {"kind": "text", "title": "Draft", "content": "Private draft"},
    )
    assert product.status_code == 200, product.text
    p = product.json()["result"]["object"]
    shares = []
    for n, role in enumerate(ROLES):
        r, _ = send(
            api,
            f"/work-products/{p['product_id']}/shares",
            f"share-{n}",
            "work_products.shares.create",
            {
                "product_id": p["product_id"],
                "product_version": p["version"],
                "recipient_role": role,
            },
        )
        assert r.status_code == 200, r.text
        shares.append(r.json()["result"]["ref"])
    return p, shares


def removed_write(view, cmd, auth, oid, *, removed=True):
    old = max(
        (x for x in view.objects if x.ref.kind == "product" and x.ref.object_id == oid),
        key=lambda x: x.ref.version,
    )
    product = C.WorkProductVersion.model_validate(old.content).model_copy(
        update={
            "version": old.ref.version + 1,
            "removed_at": datetime.now(timezone.utc) if removed else None,
            "executor": auth.executor,
        }
    )
    return Mutation(
        writes=(
            ObjectWrite(
                ref=old.ref.model_copy(update={"version": product.version}),
                expected_head=old.ref.version,
                content=product.model_dump(mode="json"),
                dependencies=references(product.model_dump(mode="json")),
            ),
        )
    )


def test_product_only_agent_removal_revokes_hidden_shares_without_scope_expansion(workspace_api):
    api = workspace_api
    app, c, store, owner, h = api
    product, shares = make_product_and_shares(api)
    oid = product["product_id"]
    grant = C.DelegationGrant(
        id="remover",
        session_id=owner.session_id,
        actor_id="learner",
        executor=C.Executor(id="remove-agent", kind="external_agent", delegation_id="remover"),
        capabilities=("read", "act"),
        allowed_objects=(oid,),
        allowed_actions=("work_products.versions.create",),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    agent = store.authenticate(owner.session_id, store.issue_delegation(owner, grant))
    assert not any(x.ref.kind == "share" for x in store.view(agent).objects)
    cmd = command(store.view(agent), "remove", "work_products.versions.create")
    result = store.execute(agent, cmd, lambda v, c, a: removed_write(v, c, a, oid))
    assert all(r.kind == "product" for r in result.objects)
    public = app.state.gateway.public_result(agent, result)
    assert not any(ref["kind"] == "share" for ref in public["objects"])
    assert all(role not in str(public) for role in ROLES)
    assert public["result"]["removals"][0]["all_active_shares_revoked"]
    assert (
        public["result"]["removals"][0]["visible_revocations"] == []
        and not public["result"]["removals"][0]["sharing_complete"]
    )
    assert store.execute(
        agent, cmd, lambda *_: (_ for _ in ()).throw(AssertionError("reentry"))
    ).replayed
    assert store.request_result(agent, "remove")[1].transaction_id == result.transaction_id
    heads = {}
    for record in store.view(owner).objects:
        if record.ref.kind == "share" and (
            record.ref.object_id not in heads
            or record.ref.version > heads[record.ref.object_id].ref.version
        ):
            heads[record.ref.object_id] = record
    assert len(heads) == 2 and all(x.content["revoked_at"] is not None for x in heads.values())
    assert not any(x.ref.kind == "share" for x in store.view(agent).objects)
    for raw, role in zip(shares, ROLES):
        with pytest.raises(C.ProtocolError):
            store.read_shared_product(
                store.role_reader(owner.session_id, role), C.ObjectRef.model_validate(raw)
            )
    store.execute(
        owner,
        command(store.view(owner), "restore", "work_products.versions.create"),
        lambda v, c, a: removed_write(v, c, a, oid, removed=False),
    )
    for raw, role in zip(shares, ROLES):
        with pytest.raises(C.ProtocolError):
            store.read_shared_product(
                store.role_reader(owner.session_id, role), C.ObjectRef.model_validate(raw)
            )
    listing = c.get(f"/sessions/{owner.session_id}/work-products/{oid}/shares", headers=h)
    assert listing.status_code == 200, listing.text
    assert len(listing.json()["result"]["result"]["items"]) == 2
    assert all(x["revoked_at"] is not None for x in listing.json()["result"]["result"]["items"])


def test_removal_and_hidden_revocations_rollback_together(workspace_api):
    api = workspace_api
    _, _, store, auth, _ = api
    product, shares = make_product_and_shares(api)
    before = counts(store)

    def fault(stage):
        if stage == "after_objects":
            raise RuntimeError("rollback")

    with pytest.raises(RuntimeError):
        store.execute(
            auth,
            command(store.view(auth), "remove", "work_products.versions.create"),
            lambda v, c, a: removed_write(v, c, a, product["product_id"]),
            fault=fault,
        )
    assert counts(store) == before
    for ref, role in zip(shares, ROLES):
        assert (
            store.read_shared_product(
                store.role_reader(auth.session_id, role), C.ObjectRef.model_validate(ref)
            ).ref.object_id
            == product["product_id"]
        )


def test_legacy_removed_head_blocks_read_even_if_old_share_was_not_revoked(workspace_api):
    api = workspace_api
    _, _, store, auth, _ = api
    product, shares = make_product_and_shares(api)
    with store.db.transaction() as c:
        row = c.execute(
            select(v2_objects.c.record).where(v2_objects.c.id == product["product_id"])
        ).scalar_one()
        obj = C.StoredObject.model_validate_json(row)
        content = dict(obj.content)
        content["removed_at"] = datetime.now(timezone.utc).isoformat()
        c.execute(
            update(v2_objects)
            .where(v2_objects.c.id == product["product_id"])
            .values(record=C.canonical(obj.model_copy(update={"content": content})))
        )
    with pytest.raises(C.ProtocolError):
        store.read_shared_product(
            store.role_reader(auth.session_id, ROLES[0]), C.ObjectRef.model_validate(shares[0])
        )


def test_queued_role_source_share_cannot_be_used_after_removal(workspace_api):
    api = workspace_api
    app, _, store, auth, _ = api
    product, shares = make_product_and_shares(api)
    calls = []
    cmd = command(store.view(auth), "queue", "turns.create")
    job = JobRequest(
        name="v2.shared-reply",
        command=cmd.model_copy(update={"request_id": "reply"}),
        sources=(C.ObjectRef.model_validate(shares[0]),),
        context_hash="0" * 64,
    )
    result = store.execute(auth, cmd, lambda *_: Mutation(jobs=(job,)))
    app.state.extensions.register_job("v2.shared-reply", lambda *_: calls.append(True))
    store.execute(
        auth,
        command(store.view(auth), "remove", "work_products.versions.create"),
        lambda v, c, a: removed_write(v, c, a, product["product_id"]),
    )
    q = JobRepository(store.db)
    worker = Worker(
        q,
        {
            "v2.shared-reply": ClaimedHandler(
                lambda p, c: app.state.gateway.run_job("v2.shared-reply", p, claim=c)
            )
        },
    )
    assert worker.run_once() and not worker.run_once() and calls == []
    assert q.get(result.result["queued_jobs"][0])["error"] == "job_share_unavailable"


def test_operation_reference_predicate_cannot_be_retained_as_authority(foundation):
    store, auth, *_ = foundation
    predicate = store.query(auth, lambda view: view.reference_allowed)
    ref = store.view(auth).current_cycle.ref
    with pytest.raises(C.ProtocolError, match="reference view expired"):
        predicate(ref)


class PrivateAudit(C.V2):
    id: str
    session_id: str
    version: int = 1
    secret: str


class LegacyRoleReply(PrivateAudit):
    role_id: str
    prompt_messages: list[dict]


def test_unsupported_private_object_channel_fails_before_commit(foundation):
    store, auth, *_ = foundation
    store.register_object("custom_audit", PrivateAudit)
    before = counts(store)
    obj = PrivateAudit(id="audit", session_id=auth.session_id, secret="PRIVATE")
    write = ObjectWrite(
        ref=C.ObjectRef(
            session_id=auth.session_id, kind="custom_audit", object_id=obj.id, version=1
        ),
        expected_head=0,
        visible_to=("system",),
        content=obj.model_dump(mode="json"),
    )
    with pytest.raises(C.ProtocolError, match="private object channel required"):
        store.execute(
            auth,
            command(store.view(auth)),
            lambda *_: Mutation(writes=(write,), result={"ack": True}),
        )
    assert counts(store) == before


def test_old_role_reply_prompt_is_not_readable_or_replayed_to_learner(foundation):
    from sqlalchemy import insert
    from career_lab.storage.v2_tables import v2_heads
    from career_lab.storage.v2_snapshot import SnapshotService

    store, auth, *_ = foundation
    store.register_object("role_reply", LegacyRoleReply)
    obj = LegacyRoleReply(
        id="reply",
        session_id=auth.session_id,
        role_id="tech_lead",
        secret="AUDIT_ONLY",
        prompt_messages=[{"role": "system", "content": "NEVER_SHOW_INTERNAL_PROMPT"}],
    )
    ref = C.ObjectRef(session_id=auth.session_id, kind="role_reply", object_id=obj.id, version=1)
    write = ObjectWrite(
        ref=ref,
        expected_head=0,
        content=obj.model_dump(mode="json"),
        visible_to=("learner", "tech_lead"),
    )
    with pytest.raises(C.ProtocolError, match="role reply private fields forbidden"):
        store.execute(
            auth, command(store.view(auth), "new-unsafe"), lambda *_: Mutation(writes=(write,))
        )
    # Preserve an exact old shape without relabelling its original audience.
    record = C.StoredObject(
        ref=ref,
        content=obj.model_dump(mode="json"),
        visible_to=("learner", "tech_lead"),
        created_storage_revision=0,
    )
    with store.db.transaction() as c:
        c.execute(
            insert(v2_objects).values(
                session_id=auth.session_id,
                kind="role_reply",
                id=obj.id,
                version=1,
                record=C.canonical(record),
                created_revision=0,
            )
        )
        c.execute(
            insert(v2_heads).values(
                session_id=auth.session_id, kind="role_reply", id=obj.id, version=1
            )
        )
    with pytest.raises(C.ProtocolError):
        store.read(auth, ref)
    assert not any(r.ref == ref for r in store.view(auth).objects)
    role = store.role_reader(auth.session_id, "tech_lead")
    assert "NEVER_SHOW_INTERNAL_PROMPT" in store.read(role, ref).model_dump_json()
    with pytest.raises(C.ProtocolError):
        SnapshotService(store).export(auth, C.digest("source"))
    audit = SnapshotService(store).export(
        store.research_context(auth.session_id), C.digest("source")
    )
    assert any("NEVER_SHOW_INTERNAL_PROMPT" in r.model_dump_json() for r in audit.objects)


def test_exact_version_sharing_page_keeps_older_active_shares_visible(workspace_api):
    api = workspace_api
    _, c, store, auth, h = api
    product, shares = make_product_and_shares(api)
    oid = product["product_id"]
    old = next(
        x for x in store.view(auth).objects if x.ref.kind == "product" and x.ref.object_id == oid
    )
    next_product = C.WorkProductVersion.model_validate(old.content).model_copy(
        update={
            "version": 2,
            "content": "New private draft",
            "content_hash": C.digest({"content": "New private draft", "structured_payload": None}),
        }
    )
    store.execute(
        auth,
        command(store.view(auth), "edit", "work_products.versions.create"),
        lambda *_: Mutation(
            writes=(
                ObjectWrite(
                    ref=old.ref.model_copy(update={"version": 2}),
                    expected_head=1,
                    content=next_product.model_dump(mode="json"),
                    dependencies=references(next_product.model_dump(mode="json")),
                ),
            )
        ),
    )
    response = c.get(f"/sessions/{auth.session_id}/work-products", headers=h)
    assert response.status_code == 200
    page = C.WorkspaceProductPage.model_validate(response.json()["result"]["result"])
    assert page.items[0].version == 2 and page.items[0].visibility == "private"
    assert len(page.shares) == 2 and all(
        s.product.version == 1 and s.revoked_at is None for s in page.shares
    )
    direct = c.get(f"/sessions/{auth.session_id}/work-products/{oid}/shares", headers=h)
    shares_page = C.WorkspaceSharePage.model_validate(direct.json()["result"]["result"])
    assert shares_page.sharing_complete and len(shares_page.items) == 2


def test_cascade_capability_does_not_claim_complete_share_read_scope(workspace_api):
    api = workspace_api
    _, _, store, owner, _ = api
    product, _ = make_product_and_shares(api)
    grant = C.DelegationGrant(
        id="only-product",
        session_id=owner.session_id,
        actor_id="learner",
        executor=C.Executor(
            id="only-product-agent", kind="external_agent", delegation_id="only-product"
        ),
        capabilities=("read", "act"),
        allowed_objects=(product["product_id"],),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    auth = store.authenticate(owner.session_id, store.issue_delegation(owner, grant))

    def inspect_view(view):
        assert view.removal_cascade == "current_product_only"
        assert not any(x.ref.kind == "share" for x in view.objects)
        return True

    assert store.query(auth, inspect_view)
    assert store.view(auth).removal_cascade is None


def test_owner_removal_response_reports_only_visible_revocations(workspace_api):
    api = workspace_api
    app, _, store, owner, _ = api
    product, _ = make_product_and_shares(api)
    result = store.execute(
        owner,
        command(store.view(owner), "owner-remove", "work_products.versions.create"),
        lambda v, c, a: removed_write(v, c, a, product["product_id"]),
    )
    summary = app.state.gateway.public_result(owner, result)["result"]["removals"][0]
    assert summary["all_active_shares_revoked"] and summary["sharing_complete"]
    assert {x["recipient_role"] for x in summary["visible_revocations"]} == set(ROLES)
    assert all(
        x["product"]["version"] == 1 and x["ref"]["version"] == 2
        for x in summary["visible_revocations"]
    )
