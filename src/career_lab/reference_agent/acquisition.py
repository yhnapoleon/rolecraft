"""Offline candidate-copy execution. Copy outcomes never feed the compared policy."""
import time
from career_lab.contracts.v2 import ActionProposal, Command, VersionPoint, ProtocolError, digest
from .ports import PortError, require_result_binding, port_error
from .snapshot_compat import snapshot_prefix_digest, restored_cycle


def execute_copies(port, *, session_id, as_of, candidates, decision_id, lineage, split,
                   timeout=30.0, clock=time.monotonic):
    """Consume W01 snapshot/restore/remapping; do not reimplement the world engine.

    Parent checks cover both success and failure. The adapter must disable real
    external effects in restored sessions; W09 cannot infer this from an ID.
    """
    if split not in {"train", "dev", "test", "regression"}:
        raise PortError("invalid_split")
    candidates = tuple(ActionProposal.model_validate(x) for x in candidates)
    if len({x.id for x in candidates}) != len(candidates):
        raise PortError("duplicate_candidate")
    as_of = VersionPoint.model_validate(as_of)
    before = port.parent_digest(session_id)
    snapshot = port.export(session_id, as_of)
    if snapshot.session_id != session_id or any(
            getattr(snapshot.state, k) != getattr(as_of, k)
            for k in ("business_seq", "workspace_revision", "storage_revision")):
        raise PortError("snapshot_point_mismatch")
    if not any(b.end_seq == as_of.business_seq and b.storage_revision == as_of.storage_revision
               for b in snapshot.boundaries):
        raise PortError("not_complete_action_boundary")
    expected_prefix, legacy = snapshot_prefix_digest(port, snapshot)
    if not isinstance(expected_prefix, str) or len(expected_prefix) != 64:
        raise PortError("invalid_prefix_digest")
    restored_sessions = set()
    results = []
    seen = set()
    try:
        for action in candidates:
            action = ActionProposal.model_validate(action)
            if action.id in seen:
                raise PortError("duplicate_candidate")
            seen.add(action.id)
            cid = digest([decision_id, action.id, digest(action)])
            started = clock()
            row = {"decision_id": decision_id, "candidate_id": action.id,
                   "parent_session_id": session_id, "lineage": lineage.model_dump(mode="json"),
                   "source_snapshot_hash": snapshot.snapshot_hash, "split": split, "status": "unknown",
                   "actual_model_cost": None, "model_usage_known": False, "step": None, "observation": None, "job_id": None,
                   "command_request_id": "candidate-" + cid, "job_binding": None}
            try:
                target_session = "candidate-" + cid
                restored = port.restore(snapshot.model_copy(deep=True), target_session, "restore-" + cid)
                expected_state = snapshot.state.model_copy(update={"session_id": target_session, "cycle_id": restored_cycle(snapshot, restored, legacy)})
                if (getattr(restored, "parent_session_id", session_id) != session_id
                    or restored.session_id != target_session or restored.session_id in restored_sessions
                    or restored.state != expected_state or restored.prefix_digest != expected_prefix
                    or restored.external_calls != 0 or restored.source_snapshot_hash != snapshot.snapshot_hash):
                    raise PortError("unsafe_candidate_restore")
                restored_sessions.add(restored.session_id)
                row["child_session_id"] = restored.session_id
                mapped = port.remap_action(action, restored)
                env = port.environment(restored)
                command = Command(schema_version=2, request_id="candidate-" + cid,
                    expected_version=restored.state.business_seq,
                    expected_workspace_revision=restored.state.workspace_revision,
                    operation=mapped.tool, payload=mapped.arguments)
                row.update(child_session_id=restored.session_id, command=command.model_dump(mode="json"))
                outcome = env.execute(restored.session_id, command, timeout)
                _record_outcome(row, outcome, command)

            except (PortError, ProtocolError) as raw_error:
                exc = port_error(raw_error)
                row.update(status="failed", error_code=exc.code)
            row["elapsed_seconds"] = clock() - started
            # No derived "optimal", "redundant" or learner-understanding label.
            results.append(row)
    finally:
        if port.parent_digest(session_id) != before:
            raise PortError("parent_changed_during_candidate_execution")
    return results


def _record_outcome(row, outcome, command, *, expected_job=None):
    require_result_binding(outcome, command.request_id, job_id=expected_job)
    if outcome.observation and outcome.observation.session_id != row["child_session_id"]:
        raise PortError("candidate_observation_session_mismatch")
    if outcome.status == "success" and outcome.step.outcome != "success":
        raise PortError("candidate_step_outcome_mismatch")
    if outcome.step and (outcome.step.action != command.operation or any(
            ref.session_id != row["child_session_id"] for ref in outcome.step.evidence_refs)):
        raise PortError("candidate_step_mismatch")
    row.update(status=outcome.status, error_code=outcome.error_code, job_id=outcome.job_id,
               observation=outcome.observation.model_dump(mode="json") if outcome.observation else None,
               step=outcome.step.model_dump(mode="json") if outcome.step else None)
    if outcome.job_id:
        row["job_binding"] = {"session_id": row["child_session_id"],
                              "request_id": command.request_id, "job_id": outcome.job_id}
    row["binding_hash"] = digest({"command": row["command"], "job_binding": row["job_binding"],
                                  "child_session_id": row["child_session_id"]})


def resume_candidate(row, environment, *, timeout=30.0):
    """One bounded read-only poll of a previously accepted candidate job.

    This local record adapter is not a shared/public wire schema. Unknown or
    rejected polling results never replace the accepted request/job binding.
    """
    from copy import deepcopy
    result = deepcopy(row)
    command = Command.model_validate(result["command"])
    expected = {"session_id": result["child_session_id"], "request_id": command.request_id,
                "job_id": result.get("job_id")}
    if (result.get("status") not in {"pending", "unresolved"} or not expected["job_id"]
            or result.get("command_request_id") != command.request_id
            or result.get("job_binding") != expected
            or result.get("binding_hash") != digest({"command": result["command"],
                "job_binding": result["job_binding"], "child_session_id": result["child_session_id"]})):
        raise PortError("candidate_job_binding_invalid")
    if timeout <= 0:
        raise PortError("deadline_exceeded")
    try:
        outcome = environment.poll(result["child_session_id"], expected["job_id"], timeout)
        _record_outcome(result, outcome, command, expected_job=expected["job_id"])
    except (PortError, ProtocolError) as raw_error:
        exc = port_error(raw_error)
        result.update(status="unresolved", error_code=exc.code)
    return result
