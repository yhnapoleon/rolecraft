"""Complete server traces preserve authorized text; submitted quotes remain claims."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import update
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import Mutation, ObjectWrite, FeedbackReadTrace, references
from career_lab.storage.v2_tables import v2_credentials
from career_lab.storage.v2_lifecycle import point
from career_lab.api.feedback_integration import record_feedback_response
from .conftest import command
from .test_core_wiring_feedback import send, stored_bytes
from .test_core_wiring_feedback_access import setup_report, delegate, SECRET, SECRET_ID, VISIBLE


def traced_report(foundation, *, agent_writer=False):
    case = setup_report(foundation, agent_writer=agent_writer)
    store = case["store"]
    auth = case["auth"]
    old = case["report"]
    # Exact sources are read by the server builder, not supplied as a client proof.
    visible = store.read(auth, case["visible"])
    text = visible.content["content"]
    items = (old.items[0].model_copy(update={"explanation": text, "citations": ()}), old.items[1])
    report = old.model_copy(
        update={
            "id": "traced-feedback",
            "items": items,
            "rule_items": items,
            "business_response": text,
            "next_options": ("核对这份已授权资料。",),
        }
    )
    ref = case["feedback"].model_copy(update={"object_id": report.id})
    both = (case["visible"], case["hidden"])
    traces = []
    for group in ("items", "rule_items"):
        traces.extend(
            (
                FeedbackReadTrace(ref, f"/{group}/0/explanation", (case["visible"],)),
                FeedbackReadTrace(ref, f"/{group}/1/explanation", (case["hidden"],)),
            )
        )
    for path in ("/business_response", "/next_options", "/independent_understanding"):
        traces.append(FeedbackReadTrace(ref, path, (case["visible"],)))
    traces.extend(
        (
            FeedbackReadTrace(ref, "/verified_facts/0", both),
            FeedbackReadTrace(ref, "/historical_responsibilities/0", both),
        )
    )
    # The aggregate has A+B inputs; these independently built entry texts have
    # narrower complete traces and must declare that fact explicitly.
    traces.extend(
        (
            FeedbackReadTrace(
                ref, "/historical_responsibilities/0/entries/0/explanation", (case["visible"],)
            ),
            FeedbackReadTrace(
                ref, "/historical_responsibilities/0/entries/1/explanation", (case["hidden"],)
            ),
        )
    )
    write = ObjectWrite(
        ref=ref,
        expected_head=0,
        content=report.model_dump(mode="json"),
        dependencies=references(report.model_dump(mode="json")),
    )
    cmd = command(store.view(auth), "publish-traced", "feedback.create").model_copy(
        update={"payload": C.FeedbackInput(subject=case["review"]).model_dump(mode="json")}
    )
    store.execute(
        auth,
        cmd,
        lambda *_: Mutation(
            writes=(write,),
            result={"feedback": ref.model_dump(mode="json")},
            feedback_read_traces=tuple(traces),
        ),
    )
    case.update(
        feedback=ref, report=C.FeedbackV2.model_validate(store.read(auth, ref).content), command=cmd
    )
    return case


def scope(case, hidden=True):
    return tuple(
        case[key].object_id
        for key in (
            ("feedback", "review", "product", "visible", "hidden")
            if hidden
            else ("feedback", "review", "product", "visible")
        )
    )


@pytest.mark.parametrize("path", ["read", "view", "http"])
def test_fully_authorized_finite_agent_matches_owner_for_bound_report(foundation, path):
    case = traced_report(foundation)
    store = case["store"]
    owner = store.read(case["owner"], case["feedback"]).content
    auth, token = delegate(case, scope(case))
    before = stored_bytes(store, case["feedback"])
    try:
        if path == "read":
            actual = store.read(auth, case["feedback"]).content
        elif path == "view":
            actual = next(
                row.content for row in store.view(auth).objects if row.ref == case["feedback"]
            )
        else:
            with TestClient(case["app"]) as client:
                response = client.get(
                    f"/sessions/{auth.session_id}/feedback-records/{case['feedback'].object_id}",
                    headers={"Authorization": "Bearer " + token},
                )
                assert response.status_code == 200, response.text
                actual = response.json()["result"]["result"]["feedback"]
        assert actual == owner and actual["read_projection"] is None
        assert (
            actual["items"][0]["citations"] == [] and actual["items"][0]["explanation"] == VISIBLE
        )
        assert stored_bytes(store, case["feedback"]) == before
    finally:
        case["app"].state.store.close()


def test_one_missing_dependency_redacts_only_dependent_segments(foundation):
    case = traced_report(foundation)
    store = case["store"]
    auth, token = delegate(case, scope(case, False))
    before = stored_bytes(store, case["feedback"])
    try:
        value = store.read(auth, case["feedback"]).content
        assert SECRET not in C.canonical(value) and SECRET_ID not in C.canonical(value)
        assert value["items"][0] == case["report"].items[0].model_dump(mode="json")
        assert value["items"][1]["source"] == "pending"
        assert value["business_response"] == VISIBLE and value["next_options"] == list(
            case["report"].next_options
        )
        assert value["historical_responsibilities"][0]["entries"][0]["explanation"] == VISIBLE
        assert value["historical_responsibilities"][0]["entries"][1]["finding"] == "unknown"
        assert value["verified_facts"][0]["source_snapshot_hash"] is None
        assert stored_bytes(store, case["feedback"]) == before
    finally:
        case["app"].state.store.close()


def test_bound_report_shrunk_scope_replay_still_cannot_leak(foundation):
    case = traced_report(foundation, agent_writer=True)
    store = case["store"]
    auth = case["auth"].model_copy(update={"allowed_objects": scope(case, False)})
    with store.db.transaction() as conn:
        conn.execute(
            update(v2_credentials)
            .where(v2_credentials.c.id == auth.credential_id)
            .values(context=C.canonical(auth))
        )
    try:
        for result in (
            store.replay(auth, case["command"]),
            store.request_result(auth, "publish-traced")[1],
            store.execute(auth, case["command"], lambda *_: pytest.fail("reentry")),
        ):
            text = result.model_dump_json()
            assert SECRET not in text and SECRET_ID not in text and VISIBLE in text
    finally:
        case["app"].state.store.close()


def test_missing_trace_does_not_become_a_complete_boundary(foundation):
    case = setup_report(foundation)
    store = case["store"]
    auth, _ = delegate(case, scope(case))
    try:
        value = store.read(auth, case["feedback"]).content
        assert value["business_response"] != case["report"].business_response
        assert value["read_projection"] == "partial" and value["items"][0]["explanation"] == VISIBLE
    finally:
        case["app"].state.store.close()


def test_caller_cannot_forge_read_boundaries_and_content_hash_is_checked(foundation):
    case = traced_report(foundation)
    store = case["store"]
    owner = case["owner"]
    new = case["report"].model_copy(update={"id": "forged"})
    ref = case["feedback"].model_copy(update={"object_id": "forged"})
    try:
        with pytest.raises(C.ProtocolError, match="feedback boundary requires server trace"):
            store.execute(
                owner,
                command(store.view(owner), "forged"),
                lambda *_: Mutation(
                    writes=(
                        ObjectWrite(
                            ref=ref,
                            expected_head=0,
                            content=new.model_dump(mode="json"),
                            dependencies=references(new.model_dump(mode="json")),
                        ),
                    )
                ),
            )
        from career_lab.contracts.v2.projection import project_feedback_content

        damaged = new.model_dump(mode="json")
        damaged["business_response"] = "Unbound altered text"
        value, partial = project_feedback_content(damaged, lambda _: True, limited_scope=True)
        assert partial and "Unbound altered text" not in C.canonical(value)
    finally:
        case["app"].state.store.close()


def test_objection_full_authorization_preserves_its_original_text(foundation):
    case = traced_report(foundation)
    store = case["store"]
    owner = case["owner"]
    text = "我对这一项有不同理解。"
    reply = store.execute(
        owner,
        send(store, owner, "response", feedback_id=case["feedback"].object_id, text=text),
        record_feedback_response,
    ).objects[0]
    auth, _ = delegate(case, (*scope(case), reply.object_id))
    try:
        assert store.read(auth, reply).content == store.read(owner, reply).content
        assert store.read(auth, reply).content["text"] == text
        assert store.read(auth, reply).content["evidence_status"] == "none_submitted"
    finally:
        case["app"].state.store.close()


def test_forged_submitted_quote_is_stored_as_unverified_then_actual_source_recheck_rejects_it(
    foundation,
):
    from career_lab.evidence.v2.assembler import EvidenceAssemblerV2, base_ref
    from career_lab.evidence.v2.ports import SourceRecord

    case = traced_report(foundation)
    store = case["store"]
    owner = case["owner"]
    source = case["visible"]
    at = point(store.view(owner).state)
    fake = C.EvidenceRefV2(**source.model_dump(), observed_at_seq=0, quote="此句不在真实来源中。")
    cmd = send(
        store,
        owner,
        "fake-quote",
        feedback_id=case["feedback"].object_id,
        kind="supplement",
        text="请核对这条补充引用。",
        evidence=[fake.model_dump(mode="json")],
    )
    try:
        result = store.execute(owner, cmd, record_feedback_response)
        record = store.read(owner, result.objects[0])
        assert record.content["evidence_status"] == "user_submitted_unverified"
        assert result.result["evidence_status"] == "user_submitted_unverified"

        class ActualStoreReader:
            def read(self, auth, ref, as_of):
                row = store.read(auth, base_ref(ref))
                assert row.ref == source
                return SourceRecord(
                    ref=C.EvidenceRefV2(**row.ref.model_dump(), observed_at_seq=0),
                    text=row.content["content"],
                    created_at=C.VersionPoint(
                        business_seq=0, workspace_revision=1, storage_revision=1
                    ),
                )

        with pytest.raises(C.ProtocolError, match="evidence quote mismatch"):
            EvidenceAssemblerV2(ActualStoreReader()).resolve(owner, fake, at)
        assert (
            store.read(owner, record.ref).content["evidence_status"] == "user_submitted_unverified"
        )
        assert case["report"].verified_facts[0].references[0].semantic_support == "not_established"
    finally:
        case["app"].state.store.close()


def test_multiple_hidden_references_remain_partial_instead_of_hiding_whole_report(foundation):
    from career_lab.contracts.v2.projection import project_feedback_content

    case = traced_report(foundation)
    raw = case["report"].model_dump(mode="json")
    try:
        hidden = {case["hidden"].object_id, case["visible"].object_id}
        projected, partial = project_feedback_content(
            raw, lambda ref: ref["object_id"] not in hidden, limited_scope=True
        )
        assert partial and len(projected["verified_facts"][0]["references"]) == 2
        assert all(
            ref["verified_ref"] is None and ref["submitted_reference_hash"] is None
            for ref in projected["verified_facts"][0]["references"]
        )
        C.FeedbackV2.model_validate(projected)
    finally:
        case["app"].state.store.close()


def test_boundary_hash_failure_does_not_fall_back_to_unbound_owner_text(foundation):
    from career_lab.contracts.v2.projection import project_feedback_content

    case = traced_report(foundation)
    raw = case["report"].model_dump(mode="json")
    raw["business_response"] = "TAMPERED_TEXT"
    try:
        projected, partial = project_feedback_content(raw, lambda _: True, limited_scope=False)
        assert partial and "TAMPERED_TEXT" not in C.canonical(projected)
    finally:
        case["app"].state.store.close()


def test_internal_snapshot_restore_rebinds_segment_hashes_without_changing_old_report(foundation):
    from career_lab.storage.v2_snapshot import SnapshotService
    from career_lab.storage.v2_store import V2Store
    from career_lab.storage.v2_remap import identity_key

    case = traced_report(foundation)
    store = case["store"]
    before = stored_bytes(store, case["feedback"])
    try:
        original = SnapshotService(store).export(
            store.research_context(case["owner"].session_id),
            C.digest("controlled boundary snapshot"),
        )
        fork = V2Store(str(store.db.engine.url))
        result, token = SnapshotService(fork).restore(original, session_id="boundary-fork")
        owner = fork.authenticate(result.session_id, token)
        mapped = [
            result.id_map[identity_key(case[key].kind, case[key].object_id)]
            for key in ("feedback", "review", "product", "visible", "hidden")
        ]
        target = case["feedback"].model_copy(
            update={"session_id": result.session_id, "object_id": mapped[0]}
        )
        grant = C.DelegationGrant(
            id="fork-reader",
            session_id=result.session_id,
            actor_id="learner",
            executor=C.Executor(id="agent", kind="external_agent", delegation_id="fork-reader"),
            capabilities=("read",),
            allowed_objects=tuple(mapped),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        agent = fork.authenticate(result.session_id, fork.issue_delegation(owner, grant))
        assert fork.read(agent, target).content == fork.read(owner, target).content
        assert fork.read(agent, target).content["read_projection"] is None
        assert stored_bytes(store, case["feedback"]) == before
        fork.db.engine.dispose()
    finally:
        case["app"].state.store.close()
