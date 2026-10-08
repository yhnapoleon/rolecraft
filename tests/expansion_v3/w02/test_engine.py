from copy import deepcopy
import json
import pytest
from career_lab.contracts.v2.core import ProtocolError
from career_lab.contracts.v2.requests import ActionInput
from career_lab.assistant.v2 import Assistant
from career_lab.contracts.v2.world import TestRequestV2 as AssistantTestRequest
from .conftest import auth, command, apply


def approve(engine, s, terms, key="request", **kwargs):
    t = engine.plan(
        s,
        command(s, "request_business", key, terms=terms, reason="按方案范围与工作项申请", **kwargs),
        auth(),
    )
    req = t.result
    s = t.snapshot
    ref = {
        "session_id": "session",
        "kind": "business_request",
        "object_id": req.id,
        "version": req.version,
    }
    return engine.plan(
        s,
        command(
            s,
            "resolve_approval",
            "resolve-" + key,
            request=ref,
            expected_request_revision=req.version,
        ),
        auth(actor="supervisor", capabilities=("read", "approve")),
    )


def test_read_repetition_and_one_time_business_milestone(engine):
    s = engine.initial("session")
    for index in range(4):
        s = engine.plan(
            s,
            command(
                s,
                "read_material",
                str(index),
                material={
                    "session_id": "session",
                    "kind": "material",
                    "object_id": "brief",
                    "version": 1,
                },
            ),
            auth(),
        ).snapshot
    assert s.source_versions["policy"] == 1 and not s.world.applied_milestones
    before = deepcopy(s)
    t = apply(engine, s)
    assert s == before
    assert [e["event_type"] for e in t.events] == ["config_applied", "initial_plan_applied"]
    assert t.last_seq - t.first_seq == 1
    assert len({e["transaction_id"] for e in t.events}) == 1
    assert t.snapshot.indexed_versions["policy"] == 1 and t.snapshot.source_versions["policy"] == 2
    again = apply(engine, t.snapshot)
    assert len(again.events) == 1 and again.snapshot.world.applied_milestones == (
        "initial_plan_applied",
    )
    for event in t.events:
        public = engine.public_event(event, t.snapshot, auth())
        assert "tech_private" not in str(public) and "world_private" not in str(public)


def test_rejected_request_closes_and_modified_request_can_succeed(engine):
    s = apply(engine, engine.initial("session"), participants=70).snapshot
    denied = approve(engine, s, {"capacity": 70})
    assert denied.result.status == "rejected" and denied.snapshot.world.resources["capacity"] == 30
    assert denied.snapshot.requests[-1].status == "rejected"
    fixed = apply(engine, denied.snapshot, participants=50).snapshot
    approved = approve(engine, fixed, {"capacity": 60}, "revised")
    assert (
        approved.result.status == "approved" and approved.snapshot.world.resources["capacity"] == 60
    )
    assert approved.snapshot.decisions[0] == denied.result
    assert approved.snapshot.requests[0].status == "rejected"


def test_approval_is_not_a_model_or_learner_capability(engine):
    s = engine.initial("session")
    t = engine.plan(
        s, command(s, "request_business", "req", terms={"capacity": 60}, reason="建议"), auth()
    )
    ref = {
        "session_id": "session",
        "kind": "business_request",
        "object_id": t.result.id,
        "version": 1,
    }
    c = command(t.snapshot, "resolve_approval", "res", request=ref, expected_request_revision=1)
    with pytest.raises(ProtocolError, match="action forbidden"):
        engine.plan(t.snapshot, c, auth())
    with pytest.raises(ProtocolError, match="approval authority required"):
        engine.plan(t.snapshot, c, auth(capabilities=("approve",)))
    assert t.snapshot.world.resources["capacity"] == 30


def test_invalid_evidence_rejected_without_resource_change(engine):
    s = apply(engine, engine.initial("session"), participants=50).snapshot
    ref = {
        "session_id": "session",
        "kind": "material",
        "object_id": "nonexistent",
        "version": 1,
        "observed_at_seq": 0,
    }
    t = approve(engine, s, {"capacity": 60}, evidence_refs=[ref])
    assert t.result.reason_code == "request_evidence_invalid" and t.result.status == "rejected"
    assert t.snapshot.world.resources["capacity"] == 30


def test_version_permissions_and_config_validation(engine):
    s = engine.initial("session")
    t = apply(engine, s)
    with pytest.raises(ProtocolError, match="version conflict"):
        engine.plan(t.snapshot, command(s, "refresh_index", "old"), auth())
    with pytest.raises(ProtocolError, match="unknown domain"):
        apply(engine, s, domains=("magic",))
    with pytest.raises(ProtocolError, match="unknown work item"):
        apply(engine, s, work_items=("free_realtime",))
    with pytest.raises(ProtocolError, match="config session mismatch"):
        apply(engine, s, session_id="foreign")
    with pytest.raises(ProtocolError, match="object forbidden"):
        engine.plan(
            s,
            command(
                s,
                "apply_config",
                "restricted",
                config=s.config.model_copy(update={"config_version": 1, "version": 2}).model_dump(
                    mode="json"
                ),
            ),
            auth(objects=("other",)),
        )


@pytest.mark.parametrize("path_index", [0, 1, 2, 3, 4])
def test_four_paths_and_unlisted_combination_use_same_engine(package, engine, path_index):
    paths = json.loads((package.root / "paths.json").read_text())
    # This fifth combination is not a registered path ID or a success allow-list.
    paths.append(
        {
            "id": "not-in-fixture",
            "domains": ["stable_faq", "policy"],
            "participants": 35,
            "update_strategy": "manual_policy",
            "work_items": ["scope_filter", "human_fallback"],
            "launch_day": 7,
            "request": {"capacity": 45},
        }
    )
    path = paths[path_index]
    terms = path.pop("request")
    path.pop("id")
    path["domains"] = tuple(path["domains"])
    path["work_items"] = tuple(path["work_items"])
    s = apply(engine, engine.initial("session"), **path).snapshot
    if terms:
        t = approve(engine, s, terms)
        s = t.snapshot
        assert t.result.status == "approved"
    execution = Assistant(package).run(
        s,
        AssistantTestRequest(query="住宿报销上限是多少？", config_version=s.config.config_version),
        auth(),
        "path-test",
    )
    if path_index == 0 or path_index == 2:
        assert execution.result.error_code == "outside_scope"
    elif path_index == 1:
        assert execution.result.status == "answered" and "400" in execution.result.answer
        assert execution.result.config.effective.update_strategy == "realtime"
    else:
        assert execution.result.error_code == "manual_verification_required"
    assert s.world.resources["capacity"] >= s.config.participants


def test_stop_examples_are_not_scores_or_config_actions(package, engine):
    examples = json.loads((package.root / "decision_examples.json").read_text())
    assert {x["decision"] for x in examples} == {"defer_with_conditions", "no_go"}
    assert all("score" not in x for x in examples)
    s = engine.initial("session")
    # Saving/discussing these products is W03/W04, not a W02 world mutation.
    assert s.world.resources == package.bundle.initial_resources
