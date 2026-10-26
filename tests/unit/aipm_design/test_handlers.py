from datetime import UTC, datetime
from pathlib import Path

import pytest

from career_lab.aipm.design.handlers import DesignReadInput, design_operations
from career_lab.aipm.design.rules import DesignFacts
from career_lab.aipm.types import AipmDesign, AipmProfile, TriageRow
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import TransactionView, session_owner

ROOT = Path(__file__).resolve().parents[3]
RULES = ROOT / "scenarios/pm_pilot/aipm-phase1/private/grading/design.json"


def record(kind, id, version, content, dependencies=()):
    return C.StoredObject(
        ref=C.ObjectRef(session_id="s", kind=kind, object_id=id, version=version),
        content=content,
        visible_to=("learner",),
        dependencies=dependencies,
        created_storage_revision=version,
    )


def world(language="zh", extra=()):
    binding = C.FileRef(path="fixture", sha256="0" * 64)
    profile = AipmProfile(
        session_id="s",
        content_revision="content-1",
        scenario_hash=binding.sha256,
        work_language=language,
        enrolled_at=datetime.now(UTC),
    )
    source = C.EvidenceRefV2(
        session_id="s",
        kind="material",
        object_id="scope",
        version=1,
        observed_at_seq=2,
        quote="No approval authority",
    )
    state = C.WorldStateV2(
        session_id="s",
        cycle_id="cycle",
        business_seq=3,
        workspace_revision=0,
        storage_revision=0,
        resources={},
    )
    objects = (record("aipm_profile", profile.id, 1, profile.model_dump(mode="json")), *extra)
    view = TransactionView(
        state=state,
        bindings=C.SessionBindings(scenario=binding, runtime=binding, evaluation=binding),
        objects=objects,
        reference_allowed=lambda ref: ref.session_id == "s" and ref.object_id != "private",
    )
    facts = DesignFacts(
        public_sources={"assistant_authority": (source,)}, need_scopes={"expenses": "expense"}
    )
    return view, session_owner("s", "credential"), facts


def draft(design_revision=1, **row_changes):
    row = dict(
        id="row1",
        need_ref="expenses",
        user_request="Approve expenses",
        target_action="approve",
        route="agent_confirmation",
        rationale="Try",
        final_authority="ai",
        revision=design_revision,
    )
    row.update(row_changes)
    return AipmDesign(
        id="design", session_id="s", revision=design_revision, rows=(TriageRow(**row),)
    )


def command(design, expected=0):
    return C.Command(
        schema_version=2,
        request_id="save",
        expected_version=3,
        expected_workspace_revision=0,
        operation="aipm.design.save",
        payload={"design": design.model_dump(mode="json"), "expected_revision": expected},
    )


def operations(facts):
    return design_operations(rules_path=RULES, facts_provider=lambda view, auth: facts)


def persisted(mutation):
    return tuple(
        record(w.ref.kind, w.ref.object_id, w.ref.version, w.content, w.dependencies)
        for w in mutation.writes
    )


@pytest.mark.parametrize("language", ["zh", "en"])
def test_save_is_pure_versioned_and_has_public_feedback(language):
    view, auth, facts = world(language)
    save, read = operations(facts)
    result = save.handler(view, command(draft()), auth)
    assert not result.state_changes and not result.jobs and not result.events
    assert all(w.visible_to == ("learner",) for w in result.writes)
    assert result.writes[0].content["rows"][0]["execution_support"] == "plan_only"
    assert result.writes[1].content["finding"] == "violation"
    assert result.writes[1].content["next_action"]["action"] == "open_step"
    restored, _, _ = world(language, persisted(result))
    response = read.handler(restored, DesignReadInput(design_id="design"), auth)
    assert response.result["design"]["revision"] == 1
    assert not response.result["feedback"][0]["stale"]


def test_old_feedback_survives_revision_and_reads_stale():
    view, auth, facts = world()
    save, read = operations(facts)
    first = save.handler(view, command(draft()), auth)
    v2, _, _ = world(extra=persisted(first))
    second = save.handler(v2, command(draft(2, target_action="explain"), 1), auth)
    v3, _, _ = world(extra=(*persisted(first), *persisted(second)))
    old = read.handler(v3, DesignReadInput(design_id="design", version=1), auth)
    assert old.result["feedback"][0]["stale"]
    assert first.writes[1].content["stale"] is False
    new = read.handler(v3, DesignReadInput(design_id="design"), auth)
    assert all(f["finding"] != "violation" for f in new.result["feedback"])


@pytest.mark.parametrize("kind", ["external_agent", "system"])
def test_nonhuman_cannot_write(kind):
    view, auth, facts = world()
    auth = auth.model_copy(update={"executor": C.Executor(id="other", kind=kind)})
    with pytest.raises(C.ProtocolError, match="human required"):
        operations(facts)[0].handler(view, command(draft()), auth)


def test_unenrolled_and_cross_session_are_rejected():
    view, auth, facts = world()
    empty = TransactionView(view.state, view.bindings, ())
    with pytest.raises(C.ProtocolError, match="not enrolled"):
        operations(facts)[0].handler(empty, command(draft()), auth)
    with pytest.raises(C.ProtocolError, match="not found"):
        operations(facts)[0].handler(
            view, command(draft().model_copy(update={"session_id": "other"})), auth
        )


def test_conflict_does_not_replace_existing_design():
    view, auth, facts = world()
    save, _ = operations(facts)
    first = save.handler(view, command(draft()), auth)
    current, _, _ = world(extra=persisted(first))
    with pytest.raises(C.ProtocolError, match="revision conflict"):
        save.handler(current, command(draft()), auth)
    with pytest.raises(C.ProtocolError, match="row revision conflict"):
        save.handler(current, command(draft(2, revision=1, target_action="explain"), 1), auth)


def test_private_or_foreign_references_fail_closed():
    view, auth, facts = world()
    for sid, id in [("s", "private"), ("other", "known")]:
        ref = C.ObjectRef(session_id=sid, kind="product", object_id=id, version=1)
        with pytest.raises(C.ProtocolError, match="not found"):
            operations(facts)[0].handler(
                view, command(draft().model_copy(update={"prd_ref": ref})), auth
            )


def test_duplicate_rows_are_rejected():
    view, auth, facts = world()
    design = draft()
    with pytest.raises(C.ProtocolError, match="duplicate id"):
        operations(facts)[0].handler(
            view, command(design.model_copy(update={"rows": design.rows * 2})), auth
        )
