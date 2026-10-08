"""Typed feedback persistence and follow-up lifecycle; controlled facts, no model."""

from datetime import datetime, timedelta, timezone
from dataclasses import replace
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from career_lab.contracts import v2 as C
from career_lab.api.app import create_app
from career_lab.api.modules import ExtensionRegistry, Operation
from career_lab.api.feedback_integration import install_feedback_recovery, record_feedback_response
from career_lab.storage.v2_store import V2Store, Mutation, ObjectWrite, references
from career_lab.storage.v2_lifecycle import point, record_review, record_submission
from career_lab.storage.v2_tables import v2_objects, v2_transactions
from .conftest import command, product_plan


def make_report(foundation, complete=True):
    store, auth, token, bindings, *_ = foundation
    product_tx = store.execute(auth, command(store.view(auth), "product"), product_plan)
    product = product_tx.objects[0]
    at = point(product_tx.state)
    review = C.ReviewInput(
        subjects=(product,), purpose="plan", scope=(), decision="defer_with_conditions"
    )
    tx = store.execute(
        auth,
        command(store.view(auth), "review", "reviews.create").model_copy(
            update={"payload": review.model_dump(mode="json")}
        ),
        record_review,
    )
    review_ref = tx.objects[0]
    window = (
        C.FeedbackActivityWindow(
            covered_from=C.VersionPoint(business_seq=0, workspace_revision=0, storage_revision=0),
            covered_through=at,
            captured_at=at,
        )
        if complete
        else None
    )
    total = C.FeedbackActivityCount(
        status="complete" if complete else "unknown",
        count=0 if complete else None,
        verified_records=0,
    )
    facts = C.VerifiedFactsSnapshot(
        subject=product,
        status="verified" if complete else "partial",
        as_of=at,
        requested_at=at,
        captured_at=at,
        source_snapshot_hash=C.digest("controlled snapshot, not production facts"),
        activity_totals={"material_read": total},
        activity_window=window,
        declared_source_count=0,
        declared_citation_count=0,
        verified_source_count=0,
        author=auth.executor,
        executor=auth.executor,
        actor_id=auth.actor_id,
        summary=(
            "Complete authorized fixture contains zero reads."
            if complete
            else "Read history completeness unknown.",
        ),
    )
    history = C.HistoricalResponsibilitiesSnapshot(
        subject=product,
        as_of=at,
        requested_at=at,
        captured_at=at,
        source_snapshot_hash=facts.source_snapshot_hash,
        completeness="unknown",
    )
    item = C.FeedbackItem(
        criterion="decision.rationale",
        label="INSUFFICIENT",
        applicability="applicable",
        source="pending",
        explanation="Conclusion quality remains pending.",
        citations=(),
    )
    report = C.FeedbackV2(
        id="feedback",
        session_id=auth.session_id,
        subject=review_ref,
        evaluation=bindings.evaluation,
        as_of=at,
        items=(item,),
        business_response="No recorded business response.",
        next_options=("Raise an objection or attach exact evidence.",),
        verified_coverage=0,
        model_coverage=0,
        verified_facts=(facts,),
        historical_responsibilities=(history,),
        rule_items=(item,),
    )
    ref = C.ObjectRef(session_id=auth.session_id, kind="feedback", object_id=report.id, version=1)
    store.execute(
        auth,
        command(store.view(auth), "feedback"),
        lambda *_: Mutation(
            writes=(
                ObjectWrite(
                    ref=ref,
                    expected_head=0,
                    content=report.model_dump(mode="json"),
                    dependencies=references(report.model_dump(mode="json")),
                ),
            )
        ),
    )
    return product, review_ref, ref, report


def app_for(store):
    registry = ExtensionRegistry()
    install_feedback_recovery(registry)
    registry.register(Operation("reviews.create", "act", C.ReviewInput, record_review))
    return create_app(str(store.db.engine.url), extensions=registry)


def send(store, auth, key, feedback_id="feedback", **changes):
    payload = C.FeedbackResponseCreate(
        feedback_id=feedback_id,
        feedback_version=1,
        kind="objection",
        text="Please reconsider the basis.",
    ).model_dump(mode="json")
    payload.update(changes)
    return command(store.view(auth), key, "feedback.responses.create").model_copy(
        update={"payload": payload}
    )


def stored_bytes(store, ref):
    with store.db.engine.connect() as conn:
        return conn.execute(
            select(v2_objects.c.record).where(
                v2_objects.c.session_id == ref.session_id,
                v2_objects.c.kind == ref.kind,
                v2_objects.c.id == ref.object_id,
                v2_objects.c.version == ref.version,
            )
        ).scalar_one()


@pytest.mark.parametrize("complete", [False, True])
def test_factual_sections_persist_and_reopen_without_reinterpretation(foundation, complete):
    store, auth, token, *_ = foundation
    product, review, ref, report = make_report(foundation, complete)
    before = stored_bytes(store, ref)
    for _ in range(2):
        app = app_for(store)
        try:
            with TestClient(app) as client:
                response = client.get(
                    f"/sessions/{auth.session_id}/feedback-records/{ref.object_id}",
                    headers={"Authorization": "Bearer " + token},
                )
                assert response.status_code == 200, response.text
                value = response.json()["result"]["result"]
                assert value["feedback"] == report.model_dump(mode="json")
                count = value["feedback"]["verified_facts"][0]["activity_totals"]["material_read"]
                assert count["count"] == (0 if complete else None)
                assert (
                    value["feedback"]["historical_responsibilities"][0]["completeness"] == "unknown"
                )
                expected = dict.fromkeys(
                    ("verified_facts", "historical_responsibilities", "rule_items"), "recorded"
                )
                assert value["sections"] == expected | {"provenance": "not_recorded"}
        finally:
            app.state.store.close()
    assert stored_bytes(store, ref) == before


def test_old_feedback_missing_sections_remains_missing_in_storage_and_wire(foundation):
    store, auth, token, *_ = foundation
    *_, ref, report = make_report(foundation)
    record = C.StoredObject.model_validate_json(stored_bytes(store, ref))
    old = {
        k: v
        for k, v in record.content.items()
        if k not in {"verified_facts", "historical_responsibilities", "rule_items"}
    }
    with store.db.transaction() as conn:
        conn.execute(
            update(v2_objects)
            .where(
                v2_objects.c.session_id == auth.session_id,
                v2_objects.c.kind == "feedback",
                v2_objects.c.id == ref.object_id,
            )
            .values(record=C.canonical(record.model_copy(update={"content": old})))
        )
    before = stored_bytes(store, ref)
    app = app_for(store)
    try:
        with TestClient(app) as client:
            value = client.get(
                f"/sessions/{auth.session_id}/feedback-records/{ref.object_id}",
                headers={"Authorization": "Bearer " + token},
            ).json()["result"]["result"]
            assert value["feedback"] == old and set(value["sections"].values()) == {"not_recorded"}
            assert C.FeedbackV2.model_validate(old).verified_facts is None
    finally:
        app.state.store.close()
    assert stored_bytes(store, ref) == before


@pytest.mark.parametrize("status", ["active", "paused", "submitted"])
def test_objection_and_supplement_are_durable_after_feedback_and_do_not_mutate_business(
    foundation, status
):
    store, auth, token, *_ = foundation
    product, review, feedback, report = make_report(foundation)
    if status == "paused":
        store.execute(
            auth,
            command(store.view(auth), "pause", "pause"),
            lambda *_: Mutation(state_changes={"status": "paused"}),
        )
    if status == "submitted":
        body = C.SubmitInput(decision="no_go", products=(product,))
        store.execute(
            auth,
            command(store.view(auth), "submit", "submit").model_copy(
                update={"payload": body.model_dump(mode="json")}
            ),
            record_submission,
            capability="submit",
        )
    before = stored_bytes(store, feedback)
    state = store.view(auth).state
    app = app_for(store)
    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer " + token}
            cmd = send(store, auth, "response")
            response = client.post(
                f"/sessions/{auth.session_id}/feedback/feedback/responses",
                headers=headers,
                json=cmd.model_dump(mode="json"),
            )
            assert response.status_code == 200, response.text
            ref = C.ObjectRef.model_validate(response.json()["result"]["response"])
            assert client.post(
                f"/sessions/{auth.session_id}/feedback/feedback/responses",
                headers=headers,
                json=cmd.model_dump(mode="json"),
            ).json()["replayed"]
            supplement = send(
                store,
                auth,
                "supplement",
                kind="supplement",
                evidence=[
                    C.EvidenceRefV2(
                        **product.model_dump(), observed_at_seq=state.business_seq
                    ).model_dump(mode="json")
                ],
            )
            response = client.post(
                f"/sessions/{auth.session_id}/feedback/feedback/responses",
                headers=headers,
                json=supplement.model_dump(mode="json"),
            )
            assert response.status_code == 200, response.text
            rows = client.get(
                f"/sessions/{auth.session_id}/feedback/feedback/responses", headers=headers
            ).json()["result"]["result"]["items"]
            assert len(rows) == 2
            assert {x["kind"] for x in rows} == {"objection", "supplement"} and all(
                x["feedback"] == feedback.model_dump(mode="json") for x in rows
            )
            assert (
                client.get(
                    f"/sessions/{auth.session_id}/feedback-responses/{ref.object_id}",
                    headers=headers,
                ).status_code
                == 200
            )
            assert (
                client.get(
                    f"/sessions/{auth.session_id}/requests/response", headers=headers
                ).status_code
                == 200
            )
    finally:
        app.state.store.close()
    after = store.view(auth).state
    assert (after.status, after.cycle_id, after.business_seq) == (
        state.status,
        state.cycle_id,
        state.business_seq,
    )
    assert stored_bytes(store, feedback) == before


def test_followup_review_links_response_and_keeps_explicit_decision(foundation):
    store, auth, *_ = foundation
    product, review, feedback, report = make_report(foundation)
    before = stored_bytes(store, feedback)
    response = store.execute(auth, send(store, auth, "response"), record_feedback_response).objects[
        0
    ]
    body = C.ReviewInput(
        subjects=(product,), purpose="plan", scope=(), decision="no_go", followup_of=(response,)
    )
    result = store.execute(
        auth,
        command(store.view(auth), "followup", "reviews.create").model_copy(
            update={"payload": body.model_dump(mode="json")}
        ),
        record_review,
    )
    saved = C.ReviewRequest.model_validate(store.read(auth, result.objects[0]).content)
    assert saved.decision == "no_go" and saved.followup_of == (response,)
    assert stored_bytes(store, feedback) == before


def test_failed_response_does_not_write_and_feedback_is_immutable(foundation):
    store, auth, *_ = foundation
    product, review, feedback, report = make_report(foundation)
    before = stored_bytes(store, feedback)
    state = store.view(auth).state
    for payload in (
        {"criterion": "unknown"},
        {"kind": "supplement", "evidence": []},
        {"text": "   "},
        {
            "evidence": [
                C.EvidenceRefV2(
                    **product.model_copy(update={"session_id": "other"}).model_dump(),
                    observed_at_seq=0,
                ).model_dump(mode="json")
            ]
        },
    ):
        with pytest.raises((C.ProtocolError, ValidationError)):
            store.execute(
                auth,
                send(store, auth, "bad-" + C.digest(payload)[:8], **payload),
                record_feedback_response,
            )
    with pytest.raises(C.ProtocolError, match="feedback record immutable"):
        store.execute(
            auth,
            command(store.view(auth), "rewrite"),
            lambda *_: Mutation(
                writes=(
                    ObjectWrite(
                        ref=feedback.model_copy(update={"version": 2}),
                        expected_head=1,
                        content=report.model_copy(
                            update={"version": 2, "business_response": "Changed past"}
                        ).model_dump(mode="json"),
                        dependencies=references(report.model_dump(mode="json")),
                    ),
                )
            ),
        )
    assert stored_bytes(store, feedback) == before and store.view(auth).state == state


def test_response_allowance_cannot_smuggle_other_writes_while_submitted(foundation):
    store, auth, *_ = foundation
    make_report(foundation)
    store.execute(
        auth,
        command(store.view(auth), "pause", "pause"),
        lambda *_: Mutation(state_changes={"status": "paused"}),
    )
    cmd = send(store, auth, "smuggle")

    def smuggle(view, cmd, auth):
        return replace(
            record_feedback_response(view, cmd, auth), state_changes={"status": "active"}
        )

    with pytest.raises(C.ProtocolError, match="feedback response only"):
        store.execute(auth, cmd, smuggle)
    assert store.view(auth).state.status == "paused"


def test_scoped_agent_response_keeps_original_executor_and_grant(foundation):
    store, owner, *_ = foundation
    product, review, feedback, report = make_report(foundation)
    grant = C.DelegationGrant(
        id="respond",
        session_id=owner.session_id,
        actor_id="learner",
        executor=C.Executor(id="agent", kind="external_agent", delegation_id="respond"),
        capabilities=("read", "act"),
        allowed_actions=(
            "feedback.responses.create",
            "feedback.responses.read",
            "feedback.responses.list",
        ),
        allowed_objects=(feedback.object_id, review.object_id, product.object_id),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    auth = store.authenticate(owner.session_id, store.issue_delegation(owner, grant))
    cmd = send(store, auth, "agent-response")
    result = store.execute(auth, cmd, record_feedback_response)
    record = store.read(auth, result.objects[0])
    assert record.creator == auth.executor and record.content[
        "executor"
    ] == auth.executor.model_dump(mode="json")
    assert store.authenticate(
        auth.session_id, store.issue_delegation(owner, grant)
    ).allowed_objects == (feedback.object_id, review.object_id, product.object_id)
    assert store.replay(auth, cmd).replayed
    store.revoke_delegation(owner, grant.id)
    with pytest.raises(C.ProtocolError):
        store.read(auth, record.ref)


def test_typed_counts_and_reference_redaction_fail_closed():
    with pytest.raises(ValidationError):
        C.FeedbackActivityCount(status="unknown", count=0)
    with pytest.raises(ValidationError):
        C.FeedbackActivityCount(status="complete", count=0, verified_records=1)
    ref = C.EvidenceRefV2(
        session_id="s",
        kind="material",
        object_id="restricted",
        version=1,
        observed_at_seq=0,
        quote="SECRET",
    )
    with pytest.raises(ValidationError):
        C.FeedbackReferenceCheck(
            submitted_reference_hash=C.digest(ref), status="unavailable", verified_ref=ref
        )
    value = C.FeedbackReferenceCheck(submitted_reference_hash=C.digest(ref), status="unavailable")
    assert "SECRET" not in value.model_dump_json() and "restricted" not in value.model_dump_json()


@pytest.mark.parametrize(
    "case",
    [
        "complete_without_window",
        "future_reference",
        "unknown_formation_count",
        "wrong_verified_count",
        "foreign_source",
    ],
)
def test_factual_provenance_and_completeness_constraints(foundation, case):
    store, auth, *_ = foundation
    product, review, feedback, report = make_report(foundation)
    raw = report.verified_facts[0].model_dump(mode="json")
    if case == "complete_without_window":
        raw["activity_window"] = None
    elif case == "unknown_formation_count":
        raw.update(as_of=None, status="unknown", activity_totals={}, activity_window=None)
    else:
        ref = C.EvidenceRefV2(**product.model_dump(), observed_at_seq=0)
        if case == "future_reference":
            ref = ref.model_copy(update={"observed_at_seq": 1})
        if case == "foreign_source":
            ref = ref.model_copy(update={"session_id": "other"})
        raw.update(
            references=[
                C.FeedbackReferenceCheck(
                    submitted_reference_hash=C.digest(ref),
                    status="exact_reference_verified",
                    verified_ref=ref,
                    valid_at_subject=True,
                ).model_dump(mode="json")
            ],
            declared_citation_count=1,
            declared_source_count=1,
            verified_source_count=0 if case == "wrong_verified_count" else 1,
        )
    with pytest.raises(ValidationError):
        C.VerifiedFactsSnapshot.model_validate(raw)


def test_restricted_agent_cannot_assert_complete_global_history(foundation):
    store, owner, *_ = foundation
    product, review, feedback, report = make_report(foundation)
    grant = C.DelegationGrant(
        id="limited-evaluator",
        session_id=owner.session_id,
        actor_id="learner",
        executor=C.Executor(id="agent", kind="external_agent", delegation_id="limited-evaluator"),
        capabilities=("read", "act"),
        allowed_objects=(product.object_id, review.object_id),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    auth = store.authenticate(owner.session_id, store.issue_delegation(owner, grant))
    candidate = report.model_copy(update={"id": "limited-report"})
    ref = feedback.model_copy(update={"object_id": candidate.id})
    with pytest.raises(C.ProtocolError, match="feedback completeness scope unknown"):
        store.execute(
            auth,
            command(store.view(auth), "limited"),
            lambda *_: Mutation(
                writes=(
                    ObjectWrite(
                        ref=ref,
                        expected_head=0,
                        content=candidate.model_dump(mode="json"),
                        dependencies=references(candidate.model_dump(mode="json")),
                    ),
                )
            ),
        )


def test_response_transaction_rolls_back_and_unrelated_followup_is_rejected(foundation):
    store, auth, *_ = foundation
    product, review, feedback, report = make_report(foundation)
    before = store.view(auth).state

    def fault(stage):
        if stage == "after_objects":
            raise RuntimeError("rollback")

    with pytest.raises(RuntimeError):
        store.execute(auth, send(store, auth, "rollback"), record_feedback_response, fault=fault)
    assert store.view(auth).state == before and not any(
        r.ref.kind == "feedback_response" for r in store.view(auth).objects
    )
    body = C.ReviewInput(subjects=(product,), purpose="plan", scope=(), followup_of=(feedback,))
    with pytest.raises(C.ProtocolError, match="review followup invalid"):
        store.execute(
            auth,
            command(store.view(auth), "wrong-followup", "reviews.create").model_copy(
                update={"payload": body.model_dump(mode="json")}
            ),
            record_review,
        )
