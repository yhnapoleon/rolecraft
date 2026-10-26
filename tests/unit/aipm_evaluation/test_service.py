import pytest

from career_lab.aipm.evaluation.service import EvaluationService
from career_lab.aipm.types import AipmDesign, TriageRow
from career_lab.contracts.v2 import (
    AuthContext,
    Command,
    Executor,
    ObjectRef,
    ProtocolError,
    ScenarioStateV2,
    SessionBindings,
    StoredObject,
    WorldStateV2,
)
from career_lab.storage.v2_store import TransactionView


def ref(kind, identity, version=1):
    return ObjectRef(
        session_id="s",
        kind=kind,
        object_id=identity,
        version=version,
        config_version=0 if kind == "config" else None,
    )


def record(reference, content):
    return StoredObject(
        ref=reference, content=content, visible_to=("learner",), created_storage_revision=0
    )


def fixture():
    # Synthetic G0 objects only. Integration tests use the actual store and worker path.
    design = AipmDesign(
        id="design",
        session_id="s",
        revision=1,
        rows=(
            TriageRow(
                id="r",
                need_ref="need-1",
                user_request="Explain policy",
                target_action="explain",
                route="retrieval_generation",
                rationale="Read the policy",
                final_authority="named_human_role",
                execution_support="supported",
            ),
        ),
    )
    objects = (
        record(ref("aipm_profile", "aipm-profile"), {"experience_revision": "aipm-phase1-v1"}),
        record(ref("aipm_design", "design"), design.model_dump(mode="json")),
        record(
            ref("product", "plan"),
            {
                "kind": "test_plan",
                "structured_payload": {
                    "type": "test_plan",
                    "cases": [
                        {
                            "id": "q",
                            "revision": 1,
                            "query": "What is the policy?",
                            "declared_expected": "Cite the policy; do not approve.",
                        },
                    ],
                },
            },
        ),
        record(ref("config", "cfg"), {"generator": "extractive"}),
    )
    # Binding fields are irrelevant to this pure handler and never exported as real content.
    from unittest.mock import Mock

    view = TransactionView(
        state=WorldStateV2(
            session_id="s",
            cycle_id="c",
            business_seq=0,
            workspace_revision=4,
            storage_revision=4,
            resources={},
        ),
        bindings=Mock(spec=SessionBindings),
        objects=objects,
        private_scenario_state=ScenarioStateV2(
            id="state",
            session_id="s",
            version=1,
            current_config=ref("config", "cfg"),
            source_versions={},
            indexed_versions={},
            material_activation={},
        ),
    )
    auth = AuthContext(
        session_id="s",
        actor_id="learner",
        executor=Executor(id="human:s", kind="human"),
        capabilities=("act", "read"),
        credential_id="owner",
    )
    return view, auth


def command(operation, payload, key="create"):
    return Command(
        schema_version=2,
        request_id=key,
        operation=operation,
        expected_version=0,
        expected_workspace_revision=4,
        payload=payload,
    )


def create(view, auth):
    return EvaluationService().create(
        view,
        command(
            "aipm.batch.create",
            {
                "design_ref": ref("aipm_design", "design").model_dump(mode="json"),
                "plan_ref": ref("product", "plan").model_dump(mode="json"),
                "selections": [
                    {"case_id": "q", "triage_row_id": "r", "coverage": "assistant_answer"}
                ],
            },
        ),
        auth,
    )


def test_batch_requires_saved_expectation_and_retains_plan_identity():
    view, auth = fixture()
    mutation = create(view, auth)
    assert mutation.state_changes == {}
    batch = mutation.result["batch"]
    assert batch["plan_ref"]["version"] == 1
    assert batch["cases"][0]["status"] == "pending"
    assert batch["cases"][0]["need_ref"] == "need-1"
    view.objects[2].content["structured_payload"]["cases"][0]["declared_expected"] = ""
    with pytest.raises(ProtocolError, match="expectation required"):
        create(view, auth)


def stored_batch(view, auth):
    from dataclasses import replace

    mutation = create(view, auth)
    write = mutation.writes[0]
    view = replace(view, objects=view.objects + (record(write.ref, write.content),))
    return view, mutation.result["batch"]


def test_prepare_accounts_for_its_own_write_and_rejects_double_preparation():
    from dataclasses import replace

    view, auth = fixture()
    view, batch = stored_batch(view, auth)
    service = EvaluationService()
    payload = {"batch_id": batch["id"], "expected_revision": 1, "action": "prepare", "case_id": "q"}
    mutation = service.update(view, command("aipm.batch.update", payload), auth)
    original = mutation.result["command"]
    assert original["request_id"] == batch["cases"][0]["request_id"]
    assert original["expected_workspace_revision"] == 5
    assert original["payload"]["declared_expected"] == "Cite the policy; do not approve."
    write = mutation.writes[0]
    view = replace(view, objects=view.objects + (record(write.ref, write.content),))
    payload["expected_revision"] = 2
    with pytest.raises(ProtocolError, match="already prepared"):
        service.update(view, command("aipm.batch.update", payload), auth)


@pytest.mark.parametrize("changed", ["resources", "sources", "index", "plan", "design"])
def test_changed_conditions_pause_without_issuing_a_command(changed):
    from dataclasses import replace

    view, auth = fixture()
    view, batch = stored_batch(view, auth)
    if changed == "resources":
        view = replace(view, state=view.state.model_copy(update={"resources": {"capacity": 3}}))
    elif changed in {"sources", "index"}:
        key = "source_versions" if changed == "sources" else "indexed_versions"
        view = replace(
            view,
            private_scenario_state=view.private_scenario_state.model_copy(
                update={key: {"policy": 2}}
            ),
        )
    else:
        kind, identity = ("product", "plan") if changed == "plan" else ("aipm_design", "design")
        view = replace(view, objects=view.objects + (record(ref(kind, identity, 2), {}),))
    mutation = EvaluationService().update(
        view,
        command(
            "aipm.batch.update",
            {
                "batch_id": batch["id"],
                "expected_revision": 1,
                "action": "prepare",
                "case_id": "q",
            },
        ),
        auth,
    )
    assert mutation.result["batch"]["pause_reason"] == "conditions_changed"
    assert "command" not in mutation.result
    assert mutation.state_changes == {}


def test_agent_cannot_create_or_assess_and_cross_session_is_denied():
    view, auth = fixture()
    agent = auth.model_copy(update={"executor": Executor(id="agent", kind="external_agent")})
    with pytest.raises(ProtocolError, match="owner required"):
        create(view, agent)
    with pytest.raises(ProtocolError, match="forbidden"):
        create(view, auth.model_copy(update={"session_id": "elsewhere"}))


def test_deterministic_case_is_unsupported_even_if_browser_requests_execution():
    view, auth = fixture()
    view.objects[1].content["rows"][0]["route"] = "deterministic"
    mutation = create(view, auth)
    assert mutation.result["batch"]["cases"][0]["status"] == "unsupported"
    assert mutation.result["batch"]["cases"][0]["coverage"] == "plan_only"
