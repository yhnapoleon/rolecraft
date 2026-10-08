"""Original 031 counterexamples plus legal positives; no semantic-quality claim."""

from dataclasses import replace
from pathlib import PurePosixPath
from urllib.parse import quote
import json
import pytest
from career_lab.contracts.v2 import ProtocolError, VersionPoint
from career_lab.runtime.context_v2 import (
    assemble_context,
    identifier_variants,
    MAX_IDENTIFIER_DECODE_ROUNDS,
)
from career_lab.storage.role_memory import resolve_stance, version_point_relation
from career_lab.runtime.model_adapter import ScriptedModel, ModelReply
from test_context import (
    package,
    catalog,
    private_sample,
    disclosure_samples,
    frame,
    owner,
    notice,
    share_receipt,
)
from test_runtime import request, generate
from test_identifier_and_stance import (
    remembered_private_source,
    stance_scenario,
    proposal_for,
    ControlledSupport,
)


@pytest.mark.parametrize(
    "form",
    ["period", "filename", "path", "double_url", "json_escape", "double_json_escape", "markdown"],
)
def test_031_identifier_echoes_are_blocked(package, catalog, private_sample, form):
    snap, req = remembered_private_source(package, catalog, private_sample)
    ref = private_sample["fact"].source
    oid = ref.object_id
    full = f"material:{oid}@{ref.version}"
    path = package.rules["material_files"][oid][str(ref.version)]
    texts = {
        "period": "The source is " + oid + ".",
        "filename": PurePosixPath(path).name,
        "path": path,
        "double_url": quote(quote(full, safe=""), safe=""),
        "json_escape": full.replace("_", chr(92) + "u005f"),
        "double_json_escape": full.replace("_", chr(92) * 2 + "u005f"),
        "markdown": f"[依据]({path}).",
    }
    value = texts[form]
    with pytest.raises(ProtocolError) as exc:
        generate(snap, owner(), req, ScriptedModel([ModelReply(text=value)]))
    assert exc.value.code == "role_output_blocked" and oid not in str(exc.value)
    with pytest.raises(ProtocolError):
        snap.require_public({"citation": value})
    with pytest.raises(ProtocolError):
        snap.require_public({"error": value})


def test_known_private_filename_without_id_and_decode_budget_fail_closed(
    package, catalog, private_sample
):
    ref = private_sample["fact"].source
    aliases = tuple(
        (
            mid,
            version,
            "materials/hidden-diagnostic.md"
            if (mid, version) == (ref.object_id, ref.version)
            else path,
        )
        for mid, version, path in catalog.material_files
    )
    changed = replace(catalog, material_files=aliases)  # isolated alias fixture, no W02 file edited
    snap = assemble_context(changed, frame(package, changed, private_sample["role"].id))
    assert private_sample["approved"] in snap.messages(owner())[0][0]["content"]
    with pytest.raises(ProtocolError):
        generate(
            snap,
            owner(),
            request(owner(), role_id=snap.role.id),
            ScriptedModel([ModelReply(text="hidden-diagnostic.md")]),
        )
    value = "material:" + ref.object_id + "@1"
    for _ in range(MAX_IDENTIFIER_DECODE_ROUNDS + 2):
        value = quote(value, safe="")
    variants, complete = identifier_variants(value)
    assert len(variants) <= MAX_IDENTIFIER_DECODE_ROUNDS + 1 and not complete
    with pytest.raises(ProtocolError):
        snap.require_public(value)


def test_public_filename_reference_and_authorized_shared_id_remain_allowed(package, catalog):
    receipt = share_receipt(2, "合法第二版内容")
    snap = assemble_context(catalog, frame(package, catalog, shares=(receipt,)))
    private = set(catalog.private_source_objects())
    material = next(
        m
        for m in catalog.materials
        if m.id in snap.role.known_materials and ("material", m.id) not in private
    )
    filename = PurePosixPath(
        package.rules["material_files"][material.id][str(material.version)]
    ).name
    text = f"见 {filename}，material:{material.id}@{material.version}，以及 product:plan@2。"
    reply, _ = generate(snap, owner(), request(owner()), ScriptedModel([ModelReply(text=text)]))
    assert reply.text == text and receipt.fragment.text in snap.messages(owner())[0][0]["content"]


def timed_stance(package, catalog):
    before, after, fact = stance_scenario(package, catalog)
    at = VersionPoint(business_seq=4, workspace_revision=5, storage_revision=10)
    proposal = replace(proposal_for(after, fact), proposed_at=at)
    assert fact.acquired_at is not None
    return before, after, fact, at, proposal


class TimeSupport(ControlledSupport):
    def __init__(self, **point_changes):
        super().__init__()
        self.point_changes = point_changes

    def check(self, *args):
        support = super().check(*args)
        return replace(support, checked_at=support.checked_at.model_copy(update=self.point_changes))


def test_three_axis_control_changes_with_complete_acquisition_window(package, catalog):
    before, after, fact, at, proposal = timed_stance(package, catalog)
    result = resolve_stance(
        before.stance_state, proposal, after.stance_facts, at, ControlledSupport()
    )
    assert result.status == "changed" and result.change is not None
    assert result.change.basis[0].acquired_at == fact.acquired_at


@pytest.mark.parametrize(
    "axis,value", [("business_seq", 5), ("workspace_revision", 6), ("storage_revision", 11)]
)
def test_future_proposal_any_axis_never_changes_state(package, catalog, axis, value):
    before, after, fact, at, proposal = timed_stance(package, catalog)
    bad = replace(proposal, proposed_at=at.model_copy(update={axis: value}))
    result = resolve_stance(before.stance_state, bad, after.stance_facts, at, ControlledSupport())
    assert (
        result.state == before.stance_state and result.change is None and result.status != "changed"
    )


@pytest.mark.parametrize(
    "axis,future,past",
    [("business_seq", 5, 3), ("workspace_revision", 6, 0), ("storage_revision", 11, 9)],
)
def test_support_window_checks_all_axes_before_adoption(package, catalog, axis, future, past):
    before, after, fact, at, proposal = timed_stance(package, catalog)
    for value in (future, past):
        result = resolve_stance(
            before.stance_state, proposal, after.stance_facts, at, TimeSupport(**{axis: value})
        )
        assert result.status == "pending" and result.reason_code == "stance_support_time_unverified"
        assert result.state == before.stance_state and result.change is None


@pytest.mark.parametrize(
    "axis,value", [("business_seq", 5), ("workspace_revision", 6), ("storage_revision", 11)]
)
def test_established_state_after_any_snapshot_axis_is_rejected(package, catalog, axis, value):
    before, after, fact, at, proposal = timed_stance(package, catalog)
    future = replace(before.stance_state, established_at=at.model_copy(update={axis: value}))
    with pytest.raises(ProtocolError, match="role stance context invalid"):
        assemble_context(
            catalog, replace(frame(package, catalog, revision=10), as_of=at, stance_state=future)
        )
    result = resolve_stance(future, proposal, after.stance_facts, at, ControlledSupport())
    assert result.state == future and result.status == "pending"


@pytest.mark.parametrize(
    "point_value",
    [
        None,
        VersionPoint(business_seq=4, workspace_revision=6, storage_revision=10),
        VersionPoint(business_seq=4, workspace_revision=5, storage_revision=11),
        VersionPoint(business_seq=3, workspace_revision=6, storage_revision=9),
    ],
)
def test_fact_acquisition_unknown_future_or_incomparable_is_pending(package, catalog, point_value):
    before, after, fact, at, proposal = timed_stance(package, catalog)
    seq = point_value.business_seq if point_value else fact.acquired_at_seq
    receipt = replace(
        fact,
        acquired_at=point_value,
        acquired_at_seq=seq,
        source=fact.source.model_copy(update={"observed_at_seq": seq}),
    )
    result = resolve_stance(before.stance_state, proposal, (receipt,), at, ControlledSupport())
    assert result.status == "pending" and result.reason_code == "stance_acquisition_time_unverified"
    assert result.state == before.stance_state and result.change is None


def test_unknown_or_incomparable_support_and_proposal_fail_closed(package, catalog):
    before, after, fact, at, proposal = timed_stance(package, catalog)
    incomparable = VersionPoint(business_seq=3, workspace_revision=6, storage_revision=10)
    assert version_point_relation(incomparable, at) == "incomparable"
    assert version_point_relation(None, at) == "unknown"
    for value in (None, incomparable):
        result = resolve_stance(
            before.stance_state,
            replace(proposal, proposed_at=value),
            after.stance_facts,
            at,
            ControlledSupport(),
        )
        assert result.status == "pending" and result.state == before.stance_state

    class MissingTime(ControlledSupport):
        def check(self, *args):
            return replace(super().check(*args), checked_at=None)

    result = resolve_stance(before.stance_state, proposal, after.stance_facts, at, MissingTime())
    assert result.status == "pending" and result.state == before.stance_state


def test_sequence_only_receipt_does_not_invent_workspace_or_storage_time(package, catalog):
    before, after, fact, at, proposal = timed_stance(package, catalog)
    event = replace(notice(), occurred_at=None)
    snap = assemble_context(
        catalog,
        replace(
            frame(package, catalog, updated=True, events=(event,), revision=10),
            as_of=at,
            stance_state=before.stance_state,
        ),
    )
    current = next(
        f
        for f in snap.stance_facts
        if f.fact_id == fact.fact_id and f.source.version == fact.source.version
    )
    assert current.acquired_at is None and current.acquired_at_seq == 4
    result = resolve_stance(
        before.stance_state, proposal, snap.stance_facts, at, ControlledSupport()
    )
    assert result.status == "pending" and result.state == before.stance_state


def test_bounded_normalization_keeps_ordinary_text_and_public_encoded_refs(package, catalog):
    snap = assemble_context(
        catalog, frame(package, catalog, shares=(share_receipt(2, "合法内容"),))
    )
    for text in ("R&D; 先核对公开资料。", quote(quote("product:plan@2", safe=""), safe="")):
        reply, _ = generate(snap, owner(), request(owner()), ScriptedModel([ModelReply(text=text)]))
        assert reply.text == text


def test_event_workspace_future_is_not_stance_fact_knowledge(package, catalog):
    before, after, fact, at, proposal = timed_stance(package, catalog)
    future_event = replace(
        notice(),
        occurred_at=VersionPoint(business_seq=4, workspace_revision=6, storage_revision=10),
    )
    snapshot = assemble_context(
        catalog,
        replace(
            frame(package, catalog, updated=True, events=(future_event,), revision=10),
            as_of=at,
            stance_state=before.stance_state,
        ),
    )
    assert {x.ref.version for x in snapshot.context.sources if x.ref.object_id == "policy"} == {1}
    assert not any(
        f.source.version == 2 and f.source.object_id == "policy" for f in snapshot.stance_facts
    )
