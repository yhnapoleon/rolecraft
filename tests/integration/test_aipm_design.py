"""Real V2Store round trip for L2 design save/read; facts are a fixture, not installer output."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from career_lab.aipm.design import OBJECT_MODELS, operations
from career_lab.aipm.design.rules import DesignFacts
from career_lab.aipm.types import AipmDesign, AipmProfile, TriageRow
from career_lab.contracts import v2 as C
from career_lab.storage.v2_store import Mutation, ObjectWrite, V2Store

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "scenarios/pm_pilot/aipm-phase1/private/grading/design.json"


@pytest.fixture
def env(tmp_path):
    store = V2Store("sqlite:///" + str(tmp_path / "v2.db"))
    store.register_object("aipm_profile", AipmProfile)
    for kind, model in OBJECT_MODELS.items():
        store.register_object(kind, model)
    ref = C.FileRef(path="bundles/frozen.json", sha256=C.digest({}))
    bindings = C.SessionBindings(scenario=ref, runtime=ref, evaluation=ref)
    config = C.AssistantConfig(id="c0", session_id="template", domains=("faq",))
    state, token = store.create_session(bindings, config, {"capacity": 30})
    auth = store.authenticate(state.session_id, token)
    sid = state.session_id
    profile = AipmProfile(
        session_id=sid,
        content_revision="aipm-design-1",
        scenario_hash=ref.sha256,
        work_language="zh",
        enrolled_at=datetime.now(UTC),
    )
    profile_ref = C.ObjectRef(session_id=sid, kind="aipm_profile", object_id=profile.id, version=1)
    write = ObjectWrite(ref=profile_ref, expected_head=0, content=profile.model_dump(mode="json"))
    store.execute(
        auth, cmd(store, auth, "enroll", "aipm.enroll"), lambda *_: Mutation(writes=(write,))
    )
    # Fixture facts: the authority quote stands in for the installed package material.
    source = C.EvidenceRefV2(
        session_id=sid, kind="aipm_profile", object_id=profile.id, version=1, observed_at_seq=0
    )
    facts = DesignFacts(
        public_sources={"assistant_authority": (source,)}, need_scopes={"expenses": "expense"}
    )
    save, read = operations(rules_path=RULES, facts_provider=lambda *_: facts)
    yield store, auth, save, read
    store.db.engine.dispose()


def cmd(store, auth, key, operation, payload=None):
    state = store.view(auth).state
    return C.Command(
        schema_version=2,
        request_id=key,
        expected_version=state.business_seq,
        expected_workspace_revision=state.workspace_revision,
        operation=operation,
        payload=payload or {},
    )


def design(sid, revision, row_revision=1, **row):
    values = (
        dict(
            id="row1",
            need_ref="expenses",
            user_request="报销最终批准",
            target_action="approve",
            route="agent_confirmation",
            rationale="",
            final_authority="ai",
            revision=row_revision,
        )
        | row
    )
    return AipmDesign(id="design", session_id=sid, revision=revision, rows=(TriageRow(**values),))


def save_design(store, auth, save, value, expected, key):
    payload = {"design": value.model_dump(mode="json"), "expected_revision": expected}
    command = cmd(store, auth, key, "aipm.design.save", payload)
    return store.execute(auth, command, save.handler)


def read_design(store, auth, read, version=None):
    page = read.request_model(design_id="design", version=version)
    return store.query(auth, lambda view: read.handler(view, page, auth)).result


def findings(result):
    return {
        (item["section_or_row_id"], item["finding"], item["stale"]) for item in result["feedback"]
    }


def test_real_store_persists_design_and_version_bound_feedback(env):
    store, auth, save, read = env
    sid = auth.session_id
    save_design(store, auth, save, design(sid, 1), 0, "s1")
    first = read_design(store, auth, read)
    assert first["ref"]["version"] == 1
    assert ("row1", "violation", False) in findings(first)
    # Correct the boundary: explanation is a legitimate retrieval answer, not a violation.
    fixed = design(
        sid,
        2,
        target_action="explain",
        route="retrieval_generation",
        final_authority="named_human_role",
        row_revision=2,
    )
    save_design(store, auth, save, fixed, 1, "s2")
    second = read_design(store, auth, read)
    assert all(finding != "violation" for _, finding, _ in findings(second))
    old = read_design(store, auth, read, version=1)
    assert ("row1", "violation", True) in findings(old)


def test_real_store_rejects_stale_revision(env):
    store, auth, save, _ = env
    save_design(store, auth, save, design(auth.session_id, 1), 0, "s1")
    with pytest.raises(C.ProtocolError) as error:
        save_design(store, auth, save, design(auth.session_id, 1), 0, "s2")
    assert error.value.code == "aipm_design_revision_conflict"
