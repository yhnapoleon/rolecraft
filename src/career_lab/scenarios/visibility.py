from career_lab.contracts.actions import Event, RoleView, WorldState
from career_lab.contracts.scenario import ScenarioSpec


def project_view(
    state: WorldState, actor_id: str, spec: ScenarioSpec, events: tuple[Event, ...] = ()
) -> RoleView:
    if actor_id not in {r.id for r in spec.roles} | {"learner"}:
        raise ValueError("unknown role")
    facts = []
    for fact in spec.facts:
        if actor_id in fact.visible_to:
            facts.append(
                fact.model_copy(update={"value": state.resources.get(fact.id, fact.value)})
            )
    materials = tuple(
        m
        for m in spec.materials
        if actor_id in m.visible_to and state.material_versions.get(m.id) == m.version
    )
    return RoleView(
        role_id=actor_id,
        state_version=state.version,
        permitted_facts=tuple(facts),
        permitted_materials=materials,
        recent_events=tuple(
            e for e in events if e.seq <= state.version and actor_id in e.visible_to
        ),
    )
