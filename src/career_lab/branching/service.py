"""Prepare remapped branches, then verify a separately mounted engine restore.

Preparation never executes the reducer, models, approvals or intervention.
"""
from dataclasses import dataclass
from typing import Protocol
from pathlib import Path

from career_lab.contracts.v2 import (
    ActionProposal, AuthContext, BranchManifest, FileRef, Lineage, RestoreResult,
    RunManifest, SnapshotExport, VersionPoint, ProtocolError, digest, read_file, canonical,
)
from .mapping import validate_prefix, make_plan, remap_snapshot
from .prefix import prefix_value, compare_prefix
from .repository import authorize


class RestorePort(Protocol):
    idempotent_restore: bool
    def lookup_restore(self, request_id: str) -> RestoreResult | None: ...
    def parent_digest(self, session_id: str) -> str: ...
    def restore(self, prepared: SnapshotExport, request_id: str) -> RestoreResult: ...
    def read_child(self, session_id: str) -> SnapshotExport: ...


class BranchService:
    def __init__(self, repository, object_codecs, event_codecs):
        self.repository = repository
        self.object_codecs, self.event_codecs = dict(object_codecs), dict(event_codecs)

    def prepare(self, auth, *, parent_ref: FileRef, parent_root: Path,
                snapshot: SnapshotExport, request_id: str, intervention: ActionProposal,
                continuation_runtime: FileRef, external_refs=()):
        parent = RunManifest.model_validate_json(read_file(parent_root, parent_ref))
        authorize(auth, parent.session_id)
        if snapshot.session_id != parent.session_id or parent.lineage.session_id != parent.session_id:
            raise ProtocolError("parent_identity_mismatch")
        if parent.lineage.run_id != parent.id:
            raise ProtocolError("parent_run_lineage_mismatch")
        if (snapshot.bindings.scenario != parent.scenario or snapshot.bindings.evaluation != parent.evaluation
                or snapshot.bindings.runtime != parent.runtime):
            raise ProtocolError("parent_binding_mismatch")
        external_refs = tuple({canonical(r): r for r in (*external_refs, *(x.ref for x in getattr(snapshot, "external_references", ())))}.values())
        # Integrity errors before a valid prefix are returned, never stored as success.
        try:
            snapshot, order = validate_prefix(snapshot, self.object_codecs, self.event_codecs, external_refs)
        except Exception as exc:
            self.repository.record_failure(auth, parent.session_id, request_id, digest([parent_ref.model_dump(mode="json"), snapshot.snapshot_hash, intervention.model_dump(mode="json")]), exc.code if isinstance(exc, ProtocolError) else type(exc).__name__)
            raise
        fork = VersionPoint(business_seq=snapshot.state.business_seq,
            workspace_revision=snapshot.state.workspace_revision,
            storage_revision=snapshot.state.storage_revision)
        bid = digest([parent_ref.model_dump(mode="json"), request_id, fork.model_dump(mode="json")])
        child_session = "branch-" + bid
        plan = make_plan(snapshot, child_session, bid, external_refs)
        # Public BranchManifest records the inherited split/component, never a new test group.
        manifest = BranchManifest(id=bid, parent_run=parent_ref, fork=fork,
            boundary=snapshot.boundaries[-1], intervention=intervention, id_map=plan.ids,
            prefix_digest=digest(prefix_value(snapshot)), executor=auth.executor,
            runtime=continuation_runtime, evaluation=parent.evaluation,
            lineage=parent.lineage.model_copy(update={"branch_id": bid, "session_id": child_session,
                "run_id": bid, "source_record_ids": (*parent.lineage.source_record_ids, parent.id)}),
            split=parent.split)
        with self.repository.operation(bid):
            record, created = self.repository.reserve(auth, parent.session_id, request_id, manifest, snapshot.snapshot_hash)
            if not created and record["status"] == "failed":
                raise ProtocolError("branch_preparation_failed",status=409)
            if not created and record["status"] != "preparing":
                return record  # Exact retry does not regenerate IDs, outputs or effects.
            try:
                before = snapshot.snapshot_hash
                prepared = remap_snapshot(snapshot, plan, self.object_codecs, self.event_codecs, order)
                child_external = tuple(plan.reference(r) for r in external_refs)
                validate_prefix(prepared, self.object_codecs, self.event_codecs, child_external)
                if snapshot.snapshot_hash != before or digest(snapshot.model_dump(mode="json", exclude={"snapshot_hash"})) != before:
                    raise ProtocolError("parent_snapshot_mutated")
                return self.repository.prepared(auth, bid, {
                    "snapshot": prepared.model_dump(mode="json"), "source_snapshot": snapshot.model_dump(mode="json"), "source_snapshot_hash": before,
                    "prepared_prefix_digest": digest(prefix_value(prepared)),
                    "parent_session": parent.session_id, "child_session": child_session,
                    "effects_executed": False, "model_calls": 0, "external_approval_calls": 0,
                    "lineage": manifest.lineage.model_dump(mode="json"), "split": manifest.split,
                })
            except Exception as exc:
                code=exc.code if isinstance(exc,ProtocolError) else type(exc).__name__
                self.repository.record_failure(auth,parent.session_id,request_id,snapshot.snapshot_hash,code)
                if isinstance(exc,ProtocolError) and exc.status<500:
                    self.repository.failed(auth,bid,code)
                # Transient storage/unknown failures keep preparing and can resume
                # under the same process lock; no partial success is returned.
                raise

    def restore(self, auth, branch_id, port: RestorePort):
        with self.repository.operation(branch_id):
            record = self.repository.get(auth, branch_id)
            if record["status"] == "restored":
                return record
            if not record["preparation"]:
                raise ProtocolError("branch_not_prepared", status=409)
            data = record["preparation"]
            expected = SnapshotExport.model_validate(data["snapshot"])
            native = hasattr(port, "read_snapshot")
            if native:
                if "source_snapshot" not in data:
                    raise ProtocolError("branch_source_snapshot_required", status=409)
                source = SnapshotExport.model_validate(data["source_snapshot"])
                from .w01_bridge import W01BranchPort
                port = W01BranchPort(port, data["child_session"], source)
            else:
                source = expected
            current_parent = port.parent_digest(data["parent_session"])
            claimed, token = self.repository.claim_restore(auth, branch_id, current_parent)
            if token is None:
                return claimed
            claim = claimed["restore"]
            before = claim["parent_digest"]
            compared = None
            try:
                if current_parent != before:
                    raise ConfirmedRestoreError("parent_changed_during_restore")
                try:
                    if claim["recovering"]:
                        lookup = getattr(port, "lookup_restore", None)
                        result = lookup(claim["request_id"]) if callable(lookup) else None
                        if result is None:
                            if not getattr(port, "idempotent_restore", False):
                                raise ProtocolError("restore_result_unresolved", status=503)
                            result = port.restore(source.model_copy(deep=True), claim["request_id"])
                    else:
                        result = port.restore(source.model_copy(deep=True), claim["request_id"])
                    if native:
                        if not port.verify_result_prefix(source, result):
                            raise ConfirmedRestoreError("restore_source_prefix_mismatch")
                        try:
                            expected = port.expected_child(source, result)
                        except ProtocolError as exc:
                            if exc.status == 503: raise
                            raise ConfirmedRestoreError(exc.code) from exc
                    if (result.session_id != data["child_session"] or result.state.session_id != data["child_session"]
                            or result.source_snapshot_hash != source.snapshot_hash
                            or result.external_calls != 0 or result.state != expected.state):
                        raise ConfirmedRestoreError("restore_identity_or_state_mismatch")
                    actual = port.read_child(result.session_id)
                    try:
                        compared = compare_prefix(expected, actual)
                    except (ValueError, TypeError):
                        raise ConfirmedRestoreError("restore_prefix_invalid") from None
                    if not compared["equal"]:
                        raise ConfirmedRestoreError("restore_prefix_mismatch")
                    if not native and result.prefix_digest != compared["actual_digest"]:
                        raise ConfirmedRestoreError("restore_prefix_identity_mismatch")
                finally:
                    if port.parent_digest(data["parent_session"]) != before:
                        raise ConfirmedRestoreError("parent_changed_during_restore")
            except Exception as exc:
                code = exc.code if isinstance(exc, ProtocolError) else type(exc).__name__
                self.repository.record_failure(auth, data["parent_session"], claim["request_id"], expected.snapshot_hash, code)
                state = "failed" if isinstance(exc, ConfirmedRestoreError) else "unresolved"
                self.repository.finish_restore(auth, branch_id, token, state,
                    evidence={"comparison": compared} if compared else None, error_code=code)
                raise
            return self.repository.finish_restore(auth, branch_id, token, "restored", evidence={
                "external_calls": 0, "prefix_equal": True, "comparison": compared,
                "child_session": result.session_id, "restore_result": result.model_dump(mode="json"),
                "intervention_executed": False,
                **({"effective_manifest": {**record["manifest"], "id_map": result.id_map}} if native else {}),
            })


class ConfirmedRestoreError(ProtocolError):
    """An observed invariant failure, distinct from unknown transport completion."""
