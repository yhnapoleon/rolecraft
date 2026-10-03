import pytest

from career_lab.contracts.actions import Action
from career_lab.scenarios.reducer import initial_state, apply_action, InvalidAction, VersionConflict
from career_lab.scenarios.visibility import project_view


def action(state, tool="read_material", arguments=None, actor="learner"):
    return Action(id=f"a{state.version}", idempotency_key=f"a{state.version}", expected_version=state.version,
                  actor_id=actor, tool=tool, arguments=arguments or {"material_id": "brief"})


def test_policy_event_and_private_projection(spec):
    state = initial_state("s", spec)
    original = state.model_dump()
    for _ in range(3):
        result = apply_action(state, action(state), spec)
        state = result.state
    assert state.material_versions["policy"] == 2
    assert state.indexed_versions["policy"] == 1
    assert original["material_versions"]["policy"] == 1
    view = project_view(state, "business_lead", spec, result.events)
    assert "tech_private" not in {m.id for m in view.permitted_materials}
    assert "tech_internal_risk" not in {f.id for f in view.permitted_facts}


def test_approval_requires_role_and_pending_request(spec):
    state = initial_state("s", spec)
    with pytest.raises(InvalidAction):
        apply_action(state, action(state, "approve_request", {"rule_id": "capacity_approved"}), spec)
    with pytest.raises(InvalidAction):
        apply_action(state, action(state, "approve_request", {"rule_id": "capacity_approved"}, "supervisor"), spec)
    state = apply_action(state, action(state, "request_capacity", {"reason": "50 users needed"}), spec).state
    state = apply_action(state, action(state, "approve_request", {"rule_id": "capacity_approved"}, "supervisor"), spec).state
    assert state.resources["capacity"] == 60
    view = project_view(state, "learner", spec)
    assert next(f.value for f in view.permitted_facts if f.id == "capacity") == 60


def test_conflict_and_unauthorized_material(spec):
    state = initial_state("s", spec)
    with pytest.raises(VersionConflict):
        apply_action(state, action(state).model_copy(update={"expected_version": 100}), spec)
    with pytest.raises(InvalidAction):
        apply_action(state, action(state, arguments={"material_id": "tech_private"}), spec)

