"""W01 snapshot port doubles only; no claim of engine replay acceptance."""
import pytest
from career_lab.contracts.v2 import (
    ActionBoundary, ActionProposal, Executor, FileRef, Lineage, RestoreResult,
    SessionBindings, SnapshotExport, VersionPoint, WorldStateV2, digest,
)
from career_lab.reference_agent.acquisition import execute_copies
from career_lab.reference_agent.ports import ActionOutcome, PortError

H = "a"*64
REF = FileRef(path="fixture.json", sha256=H)
POINT = VersionPoint(business_seq=2, workspace_revision=1, storage_revision=3)
LINEAGE = Lineage(structure_id="fixture", component_id="component", run_id="parent", session_id="s")
ACTION = ActionProposal(id="candidate", tool="read", arguments={}, purpose="inspect")


def snapshot():
    state = WorldStateV2(session_id="s", cycle_id="cycle", resources={},
                        **POINT.model_dump(exclude={"schema_version"}))
    value = SnapshotExport.model_construct(id="snapshot", session_id="s",
        bindings=SessionBindings(scenario=REF, runtime=REF, evaluation=REF), state=state,
        objects=(), events=(), boundaries=(ActionBoundary(transaction_id="tx", request_id="r",
            start_seq=0, end_seq=2, storage_revision=3),), source_digest=H, snapshot_hash=H)
    return SnapshotExport.model_validate(value.model_dump() | {
        "snapshot_hash": digest(value.model_dump(mode="json", exclude={"snapshot_hash"}))})


class SnapshotDouble:
    def __init__(self):
        self.parent = H
        self.restores = []
        self.calls = []
    def prefix_digest(self, snapshot):
        return H
    def parent_digest(self, session_id):
        return self.parent
    def export(self, session_id, as_of):
        return snapshot()
    def restore(self, snap, session_id, request_id):
        self.restores.append((session_id, request_id))
        return RestoreResult(session_id=session_id, source_snapshot_hash=snap.snapshot_hash,
            id_map={"s": session_id}, state=snap.state.model_copy(update={"session_id": session_id}),
            prefix_digest=H)
    def remap_action(self, action, restored):
        return action
    def environment(self, restored):
        return self
    def execute(self, session_id, command, timeout):
        self.calls.append((session_id, command))
        return ActionOutcome("failed", error_code="test_action_unavailable", request_id=command.request_id)


def test_candidates_are_isolated_and_inherit_parent_split():
    port = SnapshotDouble()
    results = execute_copies(port, session_id="s", as_of=POINT, candidates=[ACTION],
        decision_id="d", lineage=LINEAGE, split="dev")
    assert port.calls[0][0] != "s"
    assert results[0]["status"] == "failed"
    assert results[0]["split"] == "dev"
    assert results[0]["lineage"] == LINEAGE.model_dump(mode="json")
    assert results[0]["actual_model_cost"] is None
    assert "optimal" not in results[0] and "redundant" not in results[0]
    assert port.parent == H


def test_duplicate_candidates_rejected_before_restore():
    port = SnapshotDouble()
    with pytest.raises(PortError, match="duplicate"):
        execute_copies(port, session_id="s", as_of=POINT, candidates=[ACTION, ACTION],
            decision_id="d", lineage=LINEAGE, split="dev")
    assert not port.restores


def test_parent_change_is_not_masked_by_failed_candidate():
    class Mutating(SnapshotDouble):
        def execute(self, session_id, command, timeout):
            self.parent = "b"*64
            raise PortError("failed")
    with pytest.raises(PortError, match="parent_changed"):
        execute_copies(Mutating(), session_id="s", as_of=POINT, candidates=[ACTION],
            decision_id="d", lineage=LINEAGE, split="dev")


def test_mid_action_prefix_rejected():
    port = SnapshotDouble()
    with pytest.raises(PortError, match="snapshot_point"):
        execute_copies(port, session_id="s",
            as_of=POINT.model_copy(update={"business_seq": 1}), candidates=[ACTION],
            decision_id="d", lineage=LINEAGE, split="dev")
    assert not port.restores


def test_restore_cannot_return_parent_session():
    class BadRestore(SnapshotDouble):
        def restore(self, snap, session_id, request_id):
            return super().restore(snap, "s", request_id)
    results = execute_copies(BadRestore(), session_id="s", as_of=POINT, candidates=[ACTION],
        decision_id="d", lineage=LINEAGE, split="dev")
    assert results[0]["error_code"] == "unsafe_candidate_restore"
