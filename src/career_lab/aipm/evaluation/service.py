"""Durable evaluation bookkeeping; execution stays in tests.create and its worker.

L4 injects Gateway.request_result as a read-only lookup. No handler opens a write
transaction, creates jobs, calls a model or changes business state.
"""

from collections.abc import Callable

from career_lab.aipm.types import AipmDesign
from career_lab.api.modules import Operation, V2Response
from career_lab.contracts.v2 import (
    Command,
    ObjectRef,
    ProtocolError,
    RequestResult,
    TestPlanPayload,
    TestResultV2,
    digest,
)
from career_lab.storage.reference_graph import references
from career_lab.storage.v2_store import Mutation, ObjectWrite

from .models import (
    AbandonedAttempt,
    AssessmentRecord,
    BatchCreate,
    BatchRead,
    BatchUpdate,
    EvaluationAssessment,
    EvaluationBatch,
    EvaluationCase,
)
from .summary import summarize


def _require(view, auth, *, write=False):
    if auth.session_id != view.state.session_id or auth.actor_id != "learner":
        raise ProtocolError("aipm_forbidden", status=403)
    if write and (auth.executor.kind != "human" or "act" not in auth.capabilities):
        raise ProtocolError("aipm_owner_required", status=403)
    if auth.allowed_objects is not None:
        # Full batches carry plan, design, configuration and source identities.
        raise ProtocolError("aipm_evaluation_scope_incomplete", status=403)
    if not any(o.ref.kind == "aipm_profile" for o in view.objects):
        raise ProtocolError("aipm_not_enrolled", status=409)
    if write and view.state.status != "active":
        raise ProtocolError("aipm_practice_not_active", status=409)


def _latest(view, kind, identity):
    rows = [o for o in view.objects if o.ref.kind == kind and o.ref.object_id == identity]
    if not rows:
        raise ProtocolError("object_not_found", status=404)
    return max(rows, key=lambda o: o.ref.version)


def _saved(view, ref, kind, *, latest=False):
    if ref.kind != kind or ref.session_id != view.state.session_id:
        raise ProtocolError("object_not_found", status=404)
    row = view.get(ref)
    if latest and _latest(view, kind, ref.object_id).ref != ref:
        raise ProtocolError("aipm_input_changed", status=409)
    return row


def _baseline(view):
    private = view.private_scenario_state
    if private is None:
        raise ProtocolError("aipm_baseline_unavailable", status=409)
    return digest(
        {
            "config": private.current_config.model_dump(mode="json"),
            "sources": private.source_versions,
            "index": private.indexed_versions,
            "resources": view.state.resources,
            "milestones": view.state.applied_milestones,
            "cycle": view.state.cycle_id,
            "status": view.state.status,
        }
    )


def _changed(view, batch):
    return (
        _baseline(view) != batch.baseline_hash
        or _latest(view, "product", batch.plan_ref.object_id).ref != batch.plan_ref
        or _latest(view, "aipm_design", batch.design_ref.object_id).ref != batch.design_ref
    )


def _resendable(view, batch, row):
    """The saved original may go out again only if nothing it was bound to has moved."""
    original = Command.model_validate(row.original_command)
    return (
        not _changed(view, batch)
        and original.expected_version == view.state.business_seq
        and original.expected_workspace_revision == view.state.workspace_revision
    )


def _write(obj, kind, head):
    content = obj.model_dump(mode="json")
    ref = ObjectRef(session_id=obj.session_id, kind=kind, object_id=obj.id, version=obj.revision)
    return ObjectWrite(
        ref=ref,
        expected_head=head,
        content=content,
        visible_to=("learner",),
        dependencies=references(content),
    )


def _mutation(batch, head, **extra):
    return Mutation(
        writes=(_write(batch, "aipm_batch", head),),
        result={"batch": batch.model_dump(mode="json"), **extra},
    )


class EvaluationService:
    def __init__(self, request_reader: Callable | None = None):
        self.request_reader = request_reader

    def create(self, view, command, auth):
        _require(view, auth, write=True)
        payload = BatchCreate.model_validate(command.payload)
        plan = _saved(view, payload.plan_ref, "product", latest=True)
        if plan.content.get("kind") != "test_plan" or plan.content.get("removed"):
            raise ProtocolError("aipm_test_plan_required")
        tests = TestPlanPayload.model_validate(plan.content["structured_payload"])
        design = AipmDesign.model_validate(
            _saved(view, payload.design_ref, "aipm_design", latest=True).content
        )
        if len(tests.cases) > 20 or len({s.case_id for s in payload.selections}) != len(
            payload.selections
        ):
            raise ProtocolError("aipm_case_selection_invalid")
        private = view.private_scenario_state
        if private is None:
            raise ProtocolError("aipm_baseline_unavailable", status=409)
        config = view.get(private.current_config)
        identity = "aipm-batch-" + digest([auth.session_id, command.request_id])[:24]
        cases = []
        for selection in payload.selections:
            case = next((c for c in tests.cases if c.id == selection.case_id), None)
            row = next((r for r in design.rows if r.id == selection.triage_row_id), None)
            if case is None or row is None or not row.need_ref:
                raise ProtocolError("aipm_case_link_invalid")
            if not case.query.strip() or not (case.declared_expected or "").strip():
                raise ProtocolError("aipm_expectation_required")
            # Only the existing knowledge-answer executor is available. An answer-only
            # substep never verifies an Agent action, calculation or human handoff.
            runnable = selection.coverage == "assistant_answer" and row.route != "deterministic"
            cases.append(
                EvaluationCase(
                    id=case.id,
                    need_ref=row.need_ref,
                    triage_row_id=row.id,
                    triage_row_revision=row.revision,
                    case_revision=case.revision,
                    route=row.route,
                    coverage="assistant_answer" if runnable else "plan_only",
                    request_id="aipm-test-" + digest([identity, case.id])[:24],
                    test_case_ref=payload.plan_ref,
                    expected_ref=payload.plan_ref,
                    status="pending" if runnable else "unsupported",
                )
            )
        batch = EvaluationBatch(
            id=identity,
            session_id=auth.session_id,
            revision=1,
            design_ref=payload.design_ref,
            plan_ref=payload.plan_ref,
            config_ref=private.current_config,
            cases=tuple(cases),
            execution_mode=str(config.content.get("generator", "extractive")),
            baseline_hash=_baseline(view),
            created_by=auth.executor.id,
            monitoring=payload.monitoring,
        )
        return _mutation(batch, 0)

    def update(self, view, command, auth):
        _require(view, auth, write=True)
        payload = BatchUpdate.model_validate(command.payload)
        stored = _latest(view, "aipm_batch", payload.batch_id)
        batch = EvaluationBatch.model_validate(stored.content)
        if batch.revision != payload.expected_revision:
            raise ProtocolError("aipm_batch_revision_conflict", status=409)
        changed = _changed(view, batch)
        updates = {"revision": batch.revision + 1}
        if payload.action == "monitoring":
            updates["monitoring"] = payload.monitoring
        elif payload.action == "pause":
            updates["pause_reason"] = "user_paused"
        elif payload.action == "cancel":
            updates["cases"] = tuple(
                c.model_copy(update={"status": "cancelled"})
                if c.status == "pending" and c.original_command is None
                else c
                for c in batch.cases
            )
            updates["pause_reason"] = "user_paused"
        elif payload.action == "resume":
            updates["pause_reason"] = "conditions_changed" if changed else None
        else:
            row = next((c for c in batch.cases if c.id == payload.case_id), None)
            if row is None:
                raise ProtocolError("aipm_case_not_found", status=404)
            if payload.action == "prepare":
                if changed or batch.pause_reason:
                    updates["pause_reason"] = (
                        "conditions_changed" if changed else batch.pause_reason
                    )
                else:
                    pending = next((c for c in batch.cases if c.status == "pending"), None)
                    if row != pending or row.original_command is not None:
                        raise ProtocolError("aipm_case_already_prepared", status=409)
                    plan = TestPlanPayload.model_validate(
                        view.get(batch.plan_ref).content["structured_payload"]
                    )
                    case = next(c for c in plan.cases if c.id == row.id)
                    original = Command(
                        schema_version=2,
                        request_id=row.request_id,
                        operation="tests.create",
                        expected_version=view.state.business_seq,
                        expected_workspace_revision=view.state.workspace_revision + 1,
                        payload={
                            "query": case.query,
                            "config_version": batch.config_ref.config_version,
                            "declared_category": case.declared_category,
                            "declared_expected": case.declared_expected,
                        },
                    )
                    replacement = row.model_copy(
                        update={"original_command": original.model_dump(mode="json")}
                    )
                    updates["cases"] = tuple(
                        replacement if c.id == row.id else c for c in batch.cases
                    )
                    updated = batch.model_copy(update=updates)
                    return _mutation(
                        updated, batch.revision, command=original.model_dump(mode="json")
                    )
            elif payload.action == "reprepare":
                replacement = self._reprepare(view, auth, batch, row)
                updates["cases"] = tuple(replacement if c.id == row.id else c for c in batch.cases)
            else:
                replacement = self._reconcile(view, auth, row)
                pause = "conditions_changed" if changed else batch.pause_reason
                if replacement == row and pause == batch.pause_reason:
                    # Nothing learned: writing would move the workspace revision and make the
                    # saved original unsendable, so the reading leaves no trace.
                    return Mutation(result={"batch": batch.model_dump(mode="json")})
                updates["cases"] = tuple(replacement if c.id == row.id else c for c in batch.cases)
        if changed:
            updates["pause_reason"] = "conditions_changed"
        return _mutation(batch.model_copy(update=updates), batch.revision)

    def _lookup(self, auth, row):
        if self.request_reader is None:
            raise ProtocolError("aipm_request_lookup_unavailable", status=503)
        try:
            result = self.request_reader(auth, row.request_id)
        except ProtocolError as exc:
            if exc.code == "request_not_found":
                return None
            raise
        return RequestResult.model_validate(result)

    def _recovery(self, view, auth, batch, row):
        """Derived on every read, never stored: found, send the same original, or reprepare."""
        if self._lookup(auth, row) is not None:
            return "in_progress"
        return "send_again" if _resendable(view, batch, row) else "reprepare"

    def _reprepare(self, view, auth, batch, row):
        if row.status != "pending" or row.original_command is None:
            raise ProtocolError("aipm_case_not_prepared", status=409)
        if self._lookup(auth, row) is not None:
            # The server has it; abandoning it could run the same case twice.
            raise ProtocolError("aipm_request_exists", status=409)
        if _resendable(view, batch, row):
            raise ProtocolError("aipm_resend_available", status=409)
        abandoned = (
            *row.abandoned,
            AbandonedAttempt(
                request_id=row.request_id,
                original_command=row.original_command,
                batch_revision=batch.revision,
            ),
        )
        return row.model_copy(
            update={
                "abandoned": abandoned,
                "request_id": "aipm-test-" + digest([batch.id, row.id, len(abandoned)])[:24],
                "original_command": None,
            }
        )

    def _reconcile(self, view, auth, row):
        if row.status != "pending" or row.original_command is None:
            return row
        result = self._lookup(auth, row)
        if result is None:
            return row  # Never resubmit automatically; the learner decides on a read.
        if (
            result.session_id != auth.session_id
            or result.request_id != row.request_id
            or result.operation != "tests.create"
        ):
            raise ProtocolError("aipm_request_identity_mismatch", status=409)
        responses = [result.response, *(j.effect for j in result.jobs if j.effect is not None)]
        tests = [r.result["test"] for r in responses if "test" in r.result]
        if tests:
            test = TestResultV2.model_validate(tests[-1])
            reference = ObjectRef(
                session_id=test.session_id, kind="test", object_id=test.id, version=test.version
            )
            saved = _saved(view, reference, "test")
            if TestResultV2.model_validate(saved.content) != test:
                raise ProtocolError("aipm_result_mismatch", status=409)
            original = Command.model_validate(row.original_command)
            if (
                test.query != original.payload["query"]
                or test.config_ref.config_version != original.payload["config_version"]
            ):
                raise ProtocolError("aipm_result_mismatch", status=409)
            return row.model_copy(
                update={
                    "run_ref": reference,
                    "status": "execution_failed" if test.status == "failed" else "completed",
                }
            )
        if result.status in {"failed", "needs_context"}:
            return row.model_copy(update={"status": "execution_failed"})
        return row

    def assess(self, view, command, auth):
        _require(view, auth, write=True)
        payload = AssessmentRecord.model_validate(command.payload)
        batch = EvaluationBatch.model_validate(
            _saved(view, payload.batch_ref, "aipm_batch").content
        )
        row = next((c for c in batch.cases if c.id == payload.case_id), None)
        if row is None or row.status not in {"completed", "unsupported"}:
            raise ProtocolError("aipm_assessment_not_ready", status=409)
        if (row.status == "unsupported") != (payload.result == "unsupported"):
            raise ProtocolError("aipm_assessment_scope_mismatch")
        if not payload.reason.strip():
            raise ProtocolError("aipm_assessment_reason_required")
        item = EvaluationAssessment(
            id="aipm-assessment-" + digest([auth.session_id, command.request_id])[:24],
            session_id=auth.session_id,
            batch_ref=payload.batch_ref,
            case_id=row.id,
            case_revision=row.case_revision,
            test_case_ref=row.test_case_ref,
            expected_ref=row.expected_ref,
            run_ref=row.run_ref,
            result=payload.result,
            reason=payload.reason,
            evidence_refs=payload.evidence_refs,
            assessed_by=auth.executor.id,
        )
        return Mutation(
            writes=(_write(item, "aipm_assessment", 0),),
            result={"assessment": item.model_dump(mode="json")},
        )

    def read(self, view, payload, auth):
        _require(view, auth)
        batch = EvaluationBatch.model_validate(
            _latest(view, "aipm_batch", payload.batch_id).content
        )
        if _changed(view, batch):
            batch = batch.model_copy(update={"pause_reason": "conditions_changed"})
        assessments = []
        latest = {}
        for obj in sorted(view.objects, key=lambda o: o.created_storage_revision):
            if obj.ref.kind != "aipm_assessment":
                continue
            item = EvaluationAssessment.model_validate(obj.content)
            if item.batch_ref.object_id != batch.id:
                continue
            assessments.append(item.model_dump(mode="json"))
            latest[item.case_id] = item.result
        recovery = {
            c.id: self._recovery(view, auth, batch, c)
            for c in batch.cases
            if c.status == "pending" and c.original_command is not None and self.request_reader
        }
        return V2Response(
            result={
                "batch": batch.model_dump(mode="json"),
                "recovery": recovery,
                "assessments": assessments,
                "summary": summarize([c.model_dump(mode="json") for c in batch.cases], latest),
            }
        )

    def operations(self):
        return (
            Operation("aipm.batch.create", "act", BatchCreate, self.create),
            Operation("aipm.batch.update", "act", BatchUpdate, self.update),
            Operation(
                "aipm.batch.read",
                "read",
                BatchRead,
                self.read,
                mutates=False,
                response_model=V2Response,
            ),
            Operation("aipm.assessment.record", "act", AssessmentRecord, self.assess),
        )


OBJECT_MODELS = {"aipm_batch": EvaluationBatch, "aipm_assessment": EvaluationAssessment}
