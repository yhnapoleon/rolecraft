"""Historical RoleContext cannot mint learner/system/research role authority."""

import pytest
from sqlalchemy import select, update
from career_lab.contracts import v2 as C
from career_lab.storage.v2_tables import v2_objects
from .conftest import command
from .test_review_r4 import role_plan


@pytest.mark.parametrize("historical_role", ["learner", "system", "research", "tech_lead"])
def test_legacy_role_context_reserved_identity_never_grants_learner_access(
    foundation, historical_role
):
    store, learner, *_ = foundation
    plan = role_plan(store, learner, ("system", "tech_lead"))
    result = store.execute(learner, command(store.view(learner)), lambda *_: plan)
    ref = result.objects[0]
    with store.db.transaction() as c:
        raw = c.execute(
            select(v2_objects.c.record).where(v2_objects.c.id == ref.object_id)
        ).scalar_one()
        original = C.StoredObject.model_validate_json(raw)
        damaged = original.model_copy(
            update={
                "content": original.content | {"role_id": historical_role},
                "visible_to": ("learner", "system", "research", "tech_lead"),
            }
        )
        c.execute(
            update(v2_objects)
            .where(v2_objects.c.id == ref.object_id)
            .values(record=C.canonical(damaged))
        )
    # Both present and historical reads use the same defensive boundary.
    for revision in (None, result.state.storage_revision):
        with pytest.raises(C.ProtocolError, match="object not found"):
            store.read(learner, ref, storage_revision=revision)
    assert not any(x.ref == ref for x in store.view(learner).objects)
    with pytest.raises(C.ProtocolError, match="object not found"):
        store.can_reference(learner, ref)
    role = store.role_reader(learner.session_id, "tech_lead")
    if historical_role == "tech_lead":
        assert "SYNTHETIC_PRIVATE_QUOTE" in store.read(role, ref).model_dump_json()
        assert any(x.ref == ref for x in store.view(role).objects)
    else:
        with pytest.raises(C.ProtocolError, match="object not found"):
            store.read(role, ref)
        assert not any(x.ref == ref for x in store.view(role).objects)
    audit = store.research_context(learner.session_id)
    assert "SYNTHETIC_PRIVATE_QUOTE" in store.read(audit, ref).model_dump_json()
    assert any(x.ref == ref for x in store.view(audit).objects)


@pytest.mark.parametrize("reserved", ["learner", "system", "research"])
def test_role_reader_cannot_mint_reserved_actor_credentials(foundation, reserved):
    store, learner, *_ = foundation
    with pytest.raises(C.ProtocolError, match="role reader reserved"):
        store.role_reader(learner.session_id, reserved)
