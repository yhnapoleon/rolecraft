"""Test-only historical service/router/worker; not a Gateway implementation."""

import json
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select

from career_lab.contracts.v2.core import (
    AuthContext,
    Command,
    ObjectRef,
    EvidenceRefV2,
    ProtocolError,
    VersionPoint,
    FileRef,
    canonical,
    digest,
)
from career_lab.contracts.v2.requests import (
    ReviewInput,
    SubmitInput,
    BeginRevisionInput,
    FeedbackInput,
)
from career_lab.contracts.v2.workspace import ReviewRequest, SubmissionV2, RevisionCycle
from career_lab.contracts.v2.evaluation import EvidencePackageV2, FeedbackV2
from career_lab.evidence.v2.assembler import EvidenceAssemblerV2, base_ref
from career_lab.rubrics.v4.feedback import FeedbackEngine
from test_w05_legacy_repository_fixture import RevisionRepository, jobs


def point(state):
    return VersionPoint(
        business_seq=state.business_seq,
        workspace_revision=state.workspace_revision,
        storage_revision=state.storage_revision,
    )


def ref(sid, kind, oid):
    return ObjectRef(session_id=sid, kind=kind, object_id=oid, version=1)


class ReviewService:
    def __init__(self, repository: RevisionRepository, engine=None, model_bytes=16000):
        self.repository, self.authority = repository, repository.authority
        self.engine = engine or FeedbackEngine()
        self.model_bytes = model_bytes

    def _access(self, conn, auth, obj):
        if obj.session_id != auth.session_id or not self.authority.can_access(conn, auth, obj):
            raise ProtocolError("not_found", status=404)

    def _bindings(self, conn, auth):
        bindings = self.authority.bindings(conn, auth)
        if bindings.rules_revision != "rules-v4":
            raise ProtocolError("rules_revision_mismatch")
        try:
            fixed = self.repository.get(conn, auth.session_id, "session_bindings", auth.session_id)
        except ProtocolError as missing:
            if missing.status != 404:
                raise
            self.repository.put(
                conn,
                auth.session_id,
                "session_bindings",
                auth.session_id,
                bindings.model_dump(mode="json"),
            )
        else:
            if fixed != bindings.model_dump(mode="json"):
                raise ProtocolError("session_bundle_changed", status=409)
        return bindings

    def _freeze(
        self,
        conn,
        auth,
        oid,
        kind,
        subjects,
        purpose,
        decision,
        as_of,
        scope,
        evidence_refs=(),
        question="",
    ):
        bindings = self._bindings(conn, auth)
        requested_at = as_of
        if kind == "review":
            points = [self.authority.reader(conn).read(auth, r, as_of).created_at for r in subjects]
            if not points or any(p is None or p != points[0] for p in points):
                raise ProtocolError("subject_point_unknown")
            as_of = points[0]
        all_policies = self.authority.policies(conn, bindings.evaluation)
        policy_ids = [p.id for p in all_policies]
        if len(policy_ids) != len(set(policy_ids)) or not policy_ids or len(policy_ids) > 24:
            raise ProtocolError("invalid_evaluation_policy")
        if len(scope) != len(set(scope)) or set(scope) - set(policy_ids):
            raise ProtocolError("unknown_review_scope")
        selected = tuple(p for p in all_policies if not scope or p.id in scope)
        if not subjects:
            raise ProtocolError("review_subject_required")
        if len(subjects) > 50:
            raise ProtocolError("too_many_subjects")
        if len({r.model_dump_json() for r in subjects}) != len(subjects):
            raise ProtocolError("duplicate_subject")
        for subject in subjects:
            if subject.kind != "product":
                raise ProtocolError("unsupported_subject")
            self._access(conn, auth, subject)
        snapshot, automatic_refs = self.authority.collect(conn, auth, subjects, as_of, decision)
        assembler = EvidenceAssemblerV2(self.authority.reader(conn), self.model_bytes)
        packages = tuple(
            assembler.assemble(
                auth=auth,
                subject_id=oid,
                subjects=subjects,
                evidence_refs=tuple(evidence_refs),
                expected_refs=tuple(automatic_refs),
                purpose=purpose,
                decision=decision,
                as_of=as_of,
                policy=policy,
                snapshot=snapshot,
                question=question,
                anchor_mode="submission" if kind == "submission" else "product_version",
                requested_at=requested_at,
            )
            for policy in selected
        )
        frozen = {
            "subject": ref(auth.session_id, kind, oid).model_dump(mode="json"),
            "evaluation": bindings.evaluation.model_dump(mode="json"),
            "as_of": as_of.model_dump(mode="json"),
            "packages": [p.model_dump(mode="json") for p in packages],
            "policies": [p.to_dict() for p in selected],
            "bindings_hash": digest(bindings),
            "model_revision": self.engine.judge.revision,
        }
        return {**frozen, "snapshot_hash": digest(frozen)}

    def execute(self, auth: AuthContext, command: Command):
        payload_types = {
            "reviews.create": ReviewInput,
            "submissions.create": SubmitInput,
            "revision_cycles.begin": BeginRevisionInput,
            "feedback.request": FeedbackInput,
        }
        if command.operation not in payload_types:
            raise ProtocolError("capability_not_installed", status=503)
        body = payload_types[command.operation].model_validate(command.payload)
        command = command.model_copy(update={"payload": body.model_dump(mode="json")})

        def perform(conn, state):
            if state.session_id != auth.session_id:
                raise ProtocolError("not_found", status=404)
            oid = digest([auth.session_id, command.operation, command.request_id])
            as_of = point(state)
            metadata = state.model_copy(
                update={
                    "workspace_revision": state.workspace_revision + 1,
                    "storage_revision": state.storage_revision + 1,
                }
            )
            if command.operation == "reviews.create":
                if state.status != "active":
                    raise ProtocolError("session_" + state.status)
                if len(body.purpose) > 200 or len(body.question) > 4000:
                    raise ProtocolError("review_text_limit")
                frozen = self._freeze(
                    conn,
                    auth,
                    oid,
                    "review",
                    body.subjects,
                    body.purpose,
                    None,
                    as_of,
                    body.scope,
                    question=body.question,
                )
                review = ReviewRequest(
                    id=oid,
                    session_id=auth.session_id,
                    subjects=body.subjects,
                    purpose=body.purpose,
                    as_of=VersionPoint.model_validate(frozen["as_of"]),
                    question=body.question,
                    scope=tuple(p["id"] for p in frozen["policies"]),
                    evaluation=FileRef.model_validate(frozen["evaluation"]),
                    executor=auth.executor,
                )
                self.repository.put(
                    conn,
                    auth.session_id,
                    "review",
                    oid,
                    {"public": review.model_dump(mode="json"), "frozen": frozen},
                )
                job_id = self.repository.enqueue(
                    conn, auth, "review", oid, command.operation, command.request_id
                )
                return {
                    "review": review.model_dump(mode="json"),
                    "job_id": job_id,
                    "as_of": point(metadata).model_dump(mode="json"),
                }, metadata
            if command.operation == "submissions.create":
                if state.status != "active":
                    raise ProtocolError("session_" + state.status)
                try:
                    cycle_record = self.repository.get(
                        conn, auth.session_id, "cycle", state.cycle_id
                    )
                except ProtocolError as missing:
                    if missing.status != 404:
                        raise
                    current_cycle = self.authority.cycle(conn, auth, state.cycle_id)
                    cycle_record = {"public": current_cycle.model_dump(mode="json")}
                current_cycle = RevisionCycle.model_validate(cycle_record["public"])
                if (
                    current_cycle.session_id != auth.session_id
                    or current_cycle.id != state.cycle_id
                    or current_cycle.status != "open"
                ):
                    raise ProtocolError("cycle_not_open", status=409)
                self.repository.put(
                    conn,
                    auth.session_id,
                    "cycle",
                    state.cycle_id,
                    cycle_record,
                    current_cycle.version,
                )
                if body.config:
                    if (
                        body.config.kind != "config"
                        or body.config.config_version != state.config_version
                    ):
                        raise ProtocolError("config_version_conflict", status=409)
                    self._access(conn, auth, body.config)
                    try:
                        EvidenceAssemblerV2(self.authority.reader(conn), self.model_bytes).resolve(
                            auth, body.config, as_of
                        )
                    except KeyError:
                        raise ProtocolError("not_found", status=404) from None
                bindings = self._bindings(conn, auth)
                frozen = self._freeze(
                    conn,
                    auth,
                    oid,
                    "submission",
                    body.products,
                    "commitment",
                    body.decision,
                    as_of,
                    (),
                    body.evidence_refs,
                )
                cycle_ref = ObjectRef(
                    session_id=auth.session_id,
                    kind="cycle",
                    object_id=state.cycle_id,
                    version=current_cycle.version,
                )
                submission = SubmissionV2(
                    id=oid,
                    session_id=auth.session_id,
                    cycle=cycle_ref,
                    decision=body.decision,
                    products=body.products,
                    config=body.config,
                    evidence_refs=body.evidence_refs,
                    as_of=as_of,
                    scenario=bindings.scenario,
                    evaluation=bindings.evaluation,
                    executor=auth.executor,
                )
                self.repository.put(
                    conn,
                    auth.session_id,
                    "submission",
                    oid,
                    {"public": submission.model_dump(mode="json"), "frozen": frozen},
                )
                closed = current_cycle.model_copy(
                    update={"version": current_cycle.version + 1, "status": "submitted"}
                )
                self.repository.put(
                    conn,
                    auth.session_id,
                    "cycle",
                    state.cycle_id,
                    {
                        "public": closed.model_dump(mode="json"),
                        "submission": ref(auth.session_id, "submission", oid).model_dump(
                            mode="json"
                        ),
                    },
                    closed.version,
                )
                after = metadata.model_copy(
                    update={"business_seq": state.business_seq + 1, "status": "submitted"}
                )
                return {
                    "submission": submission.model_dump(mode="json"),
                    "as_of": point(after).model_dump(mode="json"),
                }, after
            if command.operation == "revision_cycles.begin":
                parent = body.parent_submission
                if parent.kind != "submission" or parent.version != 1:
                    raise ProtocolError("not_found", status=404)
                self._access(conn, auth, parent)
                saved = self.repository.get(conn, auth.session_id, "submission", parent.object_id)
                submission = SubmissionV2.model_validate(saved["public"])
                if state.status != "submitted" or state.cycle_id != submission.cycle.object_id:
                    raise ProtocolError("revision_parent_not_current", status=409)
                if digest(self._bindings(conn, auth)) != saved["frozen"]["bindings_hash"]:
                    raise ProtocolError("session_bundle_changed", status=409)
                if not body.reason.strip() or len(body.reason) > 4000:
                    raise ProtocolError("revision_reason_required")
                # Parent identity determines one successor. Different concurrent
                # requests cannot fork normal revision cycles.
                cycle_id = digest(
                    [auth.session_id, parent.model_dump(mode="json"), "revision-cycle"]
                )
                after = metadata.model_copy(
                    update={
                        "business_seq": state.business_seq + 1,
                        "status": "active",
                        "cycle_id": cycle_id,
                    }
                )
                cycle = RevisionCycle(
                    id=cycle_id,
                    session_id=auth.session_id,
                    parent_submission=parent,
                    opened_at=point(after),
                    base_state_ref=digest(state),
                    reason=body.reason,
                )
                self.repository.put(
                    conn,
                    auth.session_id,
                    "cycle",
                    cycle_id,
                    {
                        "public": cycle.model_dump(mode="json"),
                        "parent_hash": digest(saved),
                        "bindings_hash": saved["frozen"]["bindings_hash"],
                    },
                )
                return {
                    "cycle": cycle.model_dump(mode="json"),
                    "as_of": point(after).model_dump(mode="json"),
                }, after
            subject = body.subject
            if subject.kind not in {"review", "submission"} or subject.version != 1:
                raise ProtocolError("not_found", status=404)
            self._access(conn, auth, subject)
            self.repository.get(conn, auth.session_id, subject.kind, subject.object_id)
            job_id = self.repository.enqueue(
                conn, auth, subject.kind, subject.object_id, command.operation, command.request_id
            )
            if body.retry:
                self.repository.retry_failed(
                    conn, job_id, auth, command.operation, command.request_id
                )
            return {"job_id": job_id, "as_of": point(metadata).model_dump(mode="json")}, metadata

        return self.repository.run(auth, command, perform)

    def get(self, auth, kind, oid, version=1):
        with self.repository.transaction() as conn:
            self.authority.validate(conn, auth, "read", "reviews.read")
            if kind not in {"review", "submission", "cycle", "feedback"}:
                raise ProtocolError("not_found", status=404)
            self._access(
                conn,
                auth,
                ObjectRef(session_id=auth.session_id, kind=kind, object_id=oid, version=version),
            )
            saved = self.repository.get(conn, auth.session_id, kind, oid, version)
            return saved["feedback"] if kind == "feedback" else saved["public"]

    def job(self, auth, job_id):
        with self.repository.transaction() as conn:
            self.authority.validate(conn, auth, "read", "reviews.read")
            row = (
                conn.execute(
                    select(jobs).where(jobs.c.id == job_id, jobs.c.session_id == auth.session_id)
                )
                .mappings()
                .first()
            )
            if not row:
                raise ProtocolError("not_found", status=404)
            self._access(conn, auth, ref(auth.session_id, row["subject_kind"], row["subject_id"]))
            return {k: row[k] for k in ["id", "status", "attempt", "error_code", "feedback_id"]}

    def evidence_links(self, auth, feedback_id):
        report = FeedbackV2.model_validate(self.get(auth, "feedback", feedback_id))
        return [
            {
                "criterion": item.criterion,
                "evidence_id": "e-" + digest(source),
                "ref": source.model_dump(mode="json"),
            }
            for item in report.items
            for source in item.citations
        ]

    def read_evidence(self, auth, feedback_id, criterion, evidence_id):
        report = FeedbackV2.model_validate(self.get(auth, "feedback", feedback_id))
        source = next(
            (
                source
                for item in report.items
                if item.criterion == criterion
                for source in item.citations
                if "e-" + digest(source) == evidence_id
            ),
            None,
        )
        if source is None:
            raise ProtocolError("not_found", status=404)
        with self.repository.transaction() as conn:
            self.authority.validate(conn, auth, "read", "reviews.read")
            self._access(conn, auth, source)
            try:
                resolved = EvidenceAssemblerV2(
                    self.authority.reader(conn), self.model_bytes
                ).resolve(auth, source, report.as_of)
            except KeyError:
                raise ProtocolError("historical_evidence_missing", status=404) from None
        return {
            "ref": resolved.ref.model_dump(mode="json"),
            "content": resolved.text,
            "as_of": report.as_of.model_dump(mode="json"),
        }

    def evaluate_job(self, job):
        with self.repository.transaction() as conn:
            self.repository.check_lease(conn, job)
            auth = AuthContext.model_validate_json(job["auth"])
            self.authority.validate(conn, auth, "act", job["operation"])
            saved = self.repository.get(
                conn, auth.session_id, job["subject_kind"], job["subject_id"]
            )
            frozen = saved["frozen"]
            payload = {k: v for k, v in frozen.items() if k != "snapshot_hash"}
            if digest(payload) != frozen["snapshot_hash"]:
                raise ProtocolError("review_snapshot_hash_mismatch")
            for package in frozen["packages"]:
                for source in [
                    *package["subjects"],
                    *[c["ref"] for c in package["candidate_evidence"]],
                ]:
                    self._access(conn, auth, base_ref(EvidenceRefV2.model_validate(source)))
        packages = tuple(EvidencePackageV2.model_validate(p) for p in frozen["packages"])
        return self.engine.evaluate(
            auth.session_id,
            ObjectRef.model_validate(frozen["subject"]),
            FileRef.model_validate(frozen["evaluation"]),
            VersionPoint.model_validate(frozen["as_of"]),
            packages,
            frozen["model_revision"],
        )

    def run_once(self):
        job = self.repository.claim()
        if job is None:
            return False
        stop = threading.Event()

        def heartbeat():
            while not stop.wait(10):
                try:
                    self.repository.renew(job)
                except Exception:
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            report, diagnostics = self.evaluate_job(job)
            self.repository.finish(job, report, diagnostics)
        except Exception as error:
            try:
                self.repository.fail(
                    job, error.code if isinstance(error, ProtocolError) else type(error).__name__
                )
            except ProtocolError as lost:
                if lost.code != "lease_lost":
                    raise
        finally:
            stop.set()
            thread.join(timeout=1)
        return True


def create_service(engine, authority, feedback_engine=None, model_bytes=16000, clock=None):
    return ReviewService(RevisionRepository(engine, authority, clock), feedback_engine, model_bytes)


def create_router(service, auth_dependency, prefix="/sessions/{session_id}"):
    router = APIRouter(prefix=prefix, tags=["reviews-v2"])

    def scoped(session_id: str, auth: AuthContext = Depends(auth_dependency)):
        if auth.session_id != session_id:
            raise HTTPException(404, "not found")
        return auth

    def call(fn):
        try:
            return fn()
        except ProtocolError as e:
            return JSONResponse(
                {"schema_version": 2, "code": e.code, "message": str(e)}, status_code=e.status
            )
        except ValidationError:
            return JSONResponse(
                {
                    "schema_version": 2,
                    "code": "invalid_request",
                    "message": "Invalid review request",
                },
                status_code=422,
            )

    def write(operation, body, auth):
        if body.operation != operation:
            raise ProtocolError("operation_mismatch")
        return service.execute(auth, body)

    @router.post("/reviews")
    def review(body: Command, auth=Depends(scoped)):
        return call(lambda: write("reviews.create", body, auth))

    @router.get("/reviews/{review_id}")
    def read_review(review_id: str, auth=Depends(scoped)):
        return call(lambda: service.get(auth, "review", review_id))

    @router.post("/revision-cycles")
    def revise(body: Command, auth=Depends(scoped)):
        return call(lambda: write("revision_cycles.begin", body, auth))

    @router.post("/submissions")
    def submit(body: Command, auth=Depends(scoped)):
        return call(lambda: write("submissions.create", body, auth))

    @router.get("/submissions/{submission_id}")
    def read_submission(submission_id: str, auth=Depends(scoped)):
        return call(lambda: service.get(auth, "submission", submission_id))

    @router.get("/revision-cycles/{cycle_id}/versions/{version}")
    def read_cycle(cycle_id: str, version: int, auth=Depends(scoped)):
        return call(lambda: service.get(auth, "cycle", cycle_id, version))

    @router.post("/review-feedback")
    def feedback(body: Command, auth=Depends(scoped)):
        return call(lambda: write("feedback.request", body, auth))

    @router.get("/review-feedback/{feedback_id}")
    def read_feedback(feedback_id: str, auth=Depends(scoped)):
        return call(lambda: service.get(auth, "feedback", feedback_id))

    @router.get("/review-jobs/{job_id}")
    def read_job(job_id: str, auth=Depends(scoped)):
        return call(lambda: service.job(auth, job_id))

    @router.get("/review-feedback/{feedback_id}/evidence")
    def evidence_links(feedback_id: str, auth=Depends(scoped)):
        return call(lambda: service.evidence_links(auth, feedback_id))

    @router.get("/review-feedback/{feedback_id}/evidence/{criterion}/{evidence_id}")
    def read_evidence(feedback_id: str, criterion: str, evidence_id: str, auth=Depends(scoped)):
        return call(lambda: service.read_evidence(auth, feedback_id, criterion, evidence_id))

    return router
