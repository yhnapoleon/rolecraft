from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import pytest
from sqlalchemy import select
from career_lab.contracts.v2 import *
from career_lab.storage.v2_store import *
from career_lab.storage.v2_tables import *
from career_lab.storage.v2_lifecycle import *
from career_lab.storage.v2_snapshot import SnapshotService
from career_lab.storage.v2_remap import identity_key
from .conftest import command, product_plan


@pytest.mark.parametrize("stage", ["after_objects", "after_events", "before_commit"])
def test_atomic_failure_rolls_back_every_table(foundation, stage):
    store, auth, *_ = foundation
    before = store.view(auth)

    def fail(actual):
        if actual == stage:
            raise RuntimeError("injected storage failure")

    def plan(v, c, a):
        p = product_plan(v, c, a)
        return Mutation(
            writes=p.writes,
            events=(
                EventDraft(type="milestone", visible_to=("learner",)),
                EventDraft(type="policy_changed", visible_to=("learner",)),
            ),
            result=p.result,
        )

    with pytest.raises(RuntimeError):
        store.execute(auth, command(before), plan, fault=fail)
    assert store.view(auth) == before
    with store.db.engine.connect() as c:
        assert not c.execute(select(v2_transactions)).all()
        assert not c.execute(select(v2_events)).all()
        assert not c.execute(select(v2_relations)).all()
    result = store.execute(auth, command(before), plan)
    assert result.state.business_seq == 2 and result.state.workspace_revision == 1


def test_concurrent_idempotency_and_conflicts(foundation):
    store, auth, *_ = foundation
    cmd = command(store.view(auth))
    with ThreadPoolExecutor(max_workers=2) as p:
        results = list(p.map(lambda _: store.execute(auth, cmd, product_plan), range(2)))
    assert sum(r.replayed for r in results) == 1
    assert results[0].transaction_id == results[1].transaction_id
    assert results[0].state.business_seq == 0  # ordinary draft saving has no business milestone
    with pytest.raises(ProtocolError, match="request id reused"):
        store.execute(auth, cmd.model_copy(update={"operation": "different"}), product_plan)
    with pytest.raises(ProtocolError, match="version conflict"):
        store.execute(auth, cmd.model_copy(update={"request_id": "second"}), product_plan)
    assert len([x for x in store.view(auth).objects if x.ref.kind == "product"]) == 1


def test_identity_session_scope_and_revoked_queued_job(foundation):
    store, auth, token, bindings, config = foundation
    r = store.execute(auth, command(store.view(auth)), product_plan)
    ref = r.objects[0]
    sid2, token2 = store.create_session(bindings, config, {"capacity": 30})
    other = store.authenticate(sid2.session_id, token2)
    with pytest.raises(ProtocolError, match="object not found"):
        store.read(other, ref)
    grant = DelegationGrant(
        id="delegate",
        session_id=auth.session_id,
        actor_id="learner",
        executor=Executor(id="agent-1", kind="external_agent", delegation_id="delegate"),
        capabilities=("read", "act"),
        allowed_actions=("save",),
        allowed_objects=(ref.object_id,),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    agent_token = store.issue_delegation(auth, grant)
    agent = store.authenticate(auth.session_id, agent_token)
    with pytest.raises(ProtocolError, match="capability forbidden"):
        store.authorize(agent, "submit")
    with pytest.raises(ProtocolError, match="request id reused"):
        store.execute(
            agent, command(TransactionView(r.state, bindings, ()), key="one"), product_plan
        )
    context = JobContextSnapshot(
        session_id=auth.session_id,
        request_id="queued",
        credential_id=agent.credential_id,
        actor=agent.executor,
        action="save",
        as_of=point(r.state),
        context_hash=digest({}),
        sources=(ref,),
    )
    assert store.guard_job(context) == agent
    store.revoke_delegation(auth, agent.credential_id)
    with pytest.raises(ProtocolError, match="credential revoked"):
        store.guard_job(context)
    with pytest.raises(ProtocolError):
        store.authenticate(auth.session_id, agent_token)
    with pytest.raises(ProtocolError):
        store.authenticate(auth.session_id, token2)


def test_review_submit_revision_keeps_old_objects(foundation):
    store, auth, *_ = foundation
    r = store.execute(auth, command(store.view(auth)), product_plan)
    product = r.objects[0]
    cmd = command(store.view(auth), "review", "review").model_copy(
        update={
            "payload": ReviewInput(
                subjects=(product,), purpose="exploration", scope=("reasoning",)
            ).model_dump(mode="json")
        }
    )
    review = store.execute(auth, cmd, record_review)
    assert review.state.status == "active" and review.state.business_seq == 0
    submit = command(store.view(auth), "submit", "submit").model_copy(
        update={
            "payload": SubmitInput(decision="no_go", products=(product,)).model_dump(mode="json")
        }
    )
    result = store.execute(auth, submit, record_submission, capability="submit")
    parent = ObjectRef.model_validate(result.result["submission"])
    old = store.read(auth, parent)
    begin = command(store.view(auth), "revise", "begin_revision").model_copy(
        update={
            "payload": BeginRevisionInput(parent_submission=parent, reason="补证").model_dump(
                mode="json"
            )
        }
    )
    revised = store.execute(auth, begin, begin_revision)
    assert revised.state.status == "active" and revised.state.cycle_id != result.state.cycle_id
    assert store.execute(auth, begin, begin_revision).replayed
    assert store.read(auth, parent) == old
    assert store.read(auth, product).ref.version == 1


def test_snapshot_exact_storage_cutoff_and_remapped_restore(foundation):
    store, auth, *_ = foundation
    research = store.research_context(auth.session_id)
    service = SnapshotService(store)

    def multi(v, c, a):
        p = product_plan(v, c, a)
        return Mutation(
            writes=p.writes,
            events=(
                EventDraft(type="applied", visible_to=("learner",)),
                EventDraft(type="policy_updated", visible_to=("learner",)),
            ),
            result=p.result,
        )

    first = store.execute(auth, command(store.view(auth), "multi"), multi)
    snapshot = service.export(research, digest("source"), storage_revision=1, fork_seq=2)
    with pytest.raises(ProtocolError, match="not action boundary"):
        service.export(research, digest("source"), storage_revision=1, fork_seq=1)
    # A later derived object at the same business seq must not enter the earlier snapshot.
    late = store.execute(
        auth, command(store.view(auth), "late"), lambda v, c, a: product_plan(v, c, a, "later")
    )
    assert late.state.business_seq == first.state.business_seq
    old = service.export(research, digest("source"), storage_revision=1, fork_seq=2)
    assert old.snapshot_hash == snapshot.snapshot_hash
    assert {x.ref.object_id for x in old.objects} == {x.ref.object_id for x in snapshot.objects}
    parent_before = store.view(auth)
    restored, new_token = service.restore(old)
    child = store.authenticate(restored.session_id, new_token)
    child_view = store.view(child)
    assert restored.external_calls == 0 and child_view.state.business_seq == 2
    assert child_view.state.resources == parent_before.state.resources
    assert all(x.ref.session_id == restored.session_id for x in child_view.objects)
    assert all(
        dep.session_id == restored.session_id for x in child_view.objects for dep in x.dependencies
    )
    assert identity_key("product", "later") not in restored.id_map
    store.execute(
        child,
        command(child_view, "child-only"),
        lambda v, c, a: product_plan(v, c, a, "child-product"),
    )
    assert store.view(auth) == parent_before
    with pytest.raises(ProtocolError):
        service.export(auth, digest("source"))
    with pytest.raises(ProtocolError):
        service.restore(old, session_id=auth.session_id)


def test_real_deterministic_approval_policy_required_and_applied(foundation):
    store, auth, *_ = foundation

    def request(v, c, a):
        cfg = AssistantConfig.model_validate(
            next(x.content for x in v.objects if x.ref.kind == "config")
        )
        basis = BusinessBasis(
            mode="proposed", config=cfg, content_hash=assistant_config_content_hash(cfg)
        )
        obj = BusinessRequest(
            basis=basis,
            id="request",
            session_id=a.session_id,
            version=1,
            requested={"capacity": 50},
            reason="扩大试点",
            as_of=point(v.state),
            executor=a.executor,
        )
        return Mutation(
            writes=(
                ObjectWrite(
                    ref=ObjectRef(
                        session_id=a.session_id,
                        kind="business_request",
                        object_id="request",
                        version=1,
                    ),
                    expected_head=0,
                    content=obj.model_dump(mode="json"),
                ),
            )
        )

    requested = store.execute(auth, command(store.view(auth), "request"), request)

    def policy(view, cmd, a):
        req = BusinessRequest.model_validate(view.get(requested.objects[0]).content)
        # Pure installed scenario policy; actual request and current capacity decide the outcome.
        allowed = req.requested["capacity"] <= 50 and view.state.resources["capacity"] == 30
        return BusinessDecision(
            id="decision",
            session_id=a.session_id,
            version=1,
            request=requested.objects[0],
            status="approved" if allowed else "rejected",
            decider="supervisor",
            rule_revision="test-scenario-capacity-v1",
            granted=req.requested if allowed else {},
            reason_code="within_tier" if allowed else "outside_tier",
            reason="Deterministic test-scenario tier",
            as_of=point(view.state),
        )

    def approve(v, c, a):
        d = policy(v, c, a)
        return Mutation(
            writes=(
                ObjectWrite(
                    ref=ObjectRef(
                        session_id=a.session_id, kind="business_decision", object_id=d.id, version=1
                    ),
                    expected_head=0,
                    content=d.model_dump(mode="json"),
                    dependencies=(d.request,),
                ),
            ),
            events=(EventDraft(type="resources_granted", visible_to=("learner",)),),
            decision=d,
        )

    cmd = command(store.view(auth), "approve", "resolve_approval")
    with pytest.raises(ProtocolError, match="approval policy required"):
        store.execute(auth, cmd, approve)
    assert store.view(auth).state.resources["capacity"] == 30
    result = store.execute(auth, cmd, approve, approval_policy=policy)
    assert result.state.resources["capacity"] == 50
    assert store.execute(auth, cmd, approve, approval_policy=policy).replayed


def test_parent_state_config_and_visibility_cannot_be_forged(foundation):
    store, auth, *_ = foundation
    view = store.view(auth)
    with pytest.raises(ProtocolError, match="config write required"):
        store.execute(
            auth,
            command(view, "bad-config"),
            lambda *_: Mutation(state_changes={"config_version": 8}),
        )

    def leak(v, c, a):
        plan = product_plan(v, c, a)
        return Mutation(
            writes=(plan.writes[0].model_copy(update={"visible_to": ("learner", "tech_lead")}),)
        )

    with pytest.raises(ProtocolError, match="product requires share"):
        store.execute(auth, command(view, "bad-visibility"), leak)
    assert store.view(auth) == view


# Imported protocol models are not pytest test classes.
globals().pop("TestRequestV2", None)
globals().pop("TestResultV2", None)
globals().pop("TestCase", None)
globals().pop("TestPlanPayload", None)
globals().pop("TestCampaign", None)

globals().pop("TestExecutionMetadata", None)
