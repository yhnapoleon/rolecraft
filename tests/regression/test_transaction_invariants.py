"""Adversarial writes and actual worker races must reach the shared transaction guard."""

from datetime import UTC, datetime, timedelta

import pytest

from career_lab.api.modules import JobEnvelope
from career_lab.contracts import v2 as C
from career_lab.storage.v2_snapshot import SnapshotService
from career_lab.storage.v2_store import Mutation, ObjectWrite, TransactionView, V2Store
from tests.contracts.expansion_v3.conftest import command, product_plan
from tests.contracts.expansion_v3.conftest import foundation as foundation
from tests.contracts.expansion_v3.test_review_r6 import ask, revise, submit

Foundation = tuple[V2Store, C.AuthContext, str, C.SessionBindings, C.AssistantConfig]


@pytest.mark.parametrize(
    "operation", ["work_products.versions.create", "workspace_imports", "save"]
)
def test_direct_extension_cannot_write_into_a_closed_cycle(
    foundation: Foundation, operation: str
) -> None:
    store, owner, *_ = foundation
    created = store.execute(owner, command(store.view(owner), "original"), product_plan)
    product = next(ref for ref in created.objects if ref.kind == "product")
    original = store.read(owner, product)
    submitted = submit(store, owner)
    revise(store, owner, submitted)
    ref = product.model_copy(update={"version": 2})
    write = ObjectWrite(
        ref=ref,
        expected_head=1,
        content={**original.content, "version": 2},
        dependencies=original.dependencies,
    )
    before = store.view(owner)
    with pytest.raises(C.ProtocolError, match="product cycle closed"):
        store.execute(
            owner, command(before, "malicious", operation), lambda *_: Mutation(writes=(write,))
        )
    after = store.view(owner)
    assert after.state == before.state and after.objects == before.objects
    assert store.read(owner, product) == original


def test_restore_uses_the_same_private_product_invariant(foundation: Foundation) -> None:
    store, owner, *_ = foundation
    store.execute(owner, command(store.view(owner), "private-work"), product_plan)
    snapshot = SnapshotService(store).export(
        store.research_context(owner.session_id), C.digest("test")
    )
    body = snapshot.model_dump(mode="json", exclude={"snapshot_hash"})
    product = next(row for row in body["objects"] if row["ref"]["kind"] == "product")
    product["visible_to"] = ["learner", "supervisor"]
    forged = C.SnapshotExport.model_validate({**body, "snapshot_hash": C.digest(body)})
    with pytest.raises(C.ProtocolError, match="product requires share"):
        SnapshotService(store).restore(forged, session_id="forged-restore")
    assert not store.contains("forged-restore")


def test_cycle_closes_while_async_result_is_being_computed(foundation: Foundation) -> None:
    store, owner, *_ = foundation

    def complete(view: TransactionView, envelope: JobEnvelope, auth: C.AuthContext) -> Mutation:
        planned = product_plan(view, envelope.command, auth, oid="late-product")
        submit(store, owner)
        return planned

    _, queue, worker, job, _ = ask(store, owner, handler=complete)
    assert worker.run_once()
    assert queue.get(job)["status"] == "needs_context"
    assert queue.get(job)["error"] == "job_session_inactive"
    assert not any(row.ref.object_id == "late-product" for row in store.view(owner).objects)
    assert not worker.run_once()


def test_authorization_revoked_while_async_result_is_being_computed(foundation: Foundation) -> None:
    store, owner, *_ = foundation
    grant = C.DelegationGrant(
        id="race-grant",
        session_id=owner.session_id,
        actor_id="learner",
        executor=C.Executor(id="external-test", kind="external_agent", delegation_id="race-grant"),
        capabilities=("read", "act"),
        allowed_actions=("turns.create",),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    agent = store.authenticate(owner.session_id, store.issue_delegation(owner, grant))

    def complete(view: TransactionView, envelope: JobEnvelope, auth: C.AuthContext) -> Mutation:
        planned = product_plan(view, envelope.command, auth, oid="revoked-result")
        store.revoke_delegation(owner, grant.id)
        return planned

    _, queue, worker, job, _ = ask(store, agent, handler=complete)
    assert worker.run_once()
    assert queue.get(job)["status"] == "failed"
    assert queue.get(job)["error"] == "credential_revoked_or_invalid"
    assert not any(row.ref.object_id == "revoked-result" for row in store.view(owner).objects)
    assert not worker.run_once()
