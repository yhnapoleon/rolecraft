import os
import secrets
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from career_lab.api.presentation import learner_state, object_list, object_response
from career_lab.assistant.service import TrainingService
from career_lab.contracts.base import Contract, Identifier, NonNegativeInt, PositiveInt
from career_lab.contracts.deliverables import Deliverable
from career_lab.errors import CodedValueError
from career_lab.jobs.repository import JobRepository
from career_lab.runtime.loop import AgentRuntime
from career_lab.runtime.model_adapter import LocalModel
from career_lab.scenarios.loader import load_scenario
from career_lab.scenarios.reducer import InvalidAction, VersionConflict
from career_lab.storage.sessions import IdempotencyConflict, SessionStore


class CreateSession(Contract):
    scenario: str = "pm_pilot"


class ActionRequest(Contract):
    tool: Identifier
    arguments: dict
    request_id: Identifier
    expected_version: NonNegativeInt


class TestRequest(Contract):
    query: str = Field(min_length=1, max_length=4000)
    config_version: NonNegativeInt
    request_id: Identifier


class ArtifactRequest(Contract):
    content: Deliverable
    request_id: Identifier


class SubmitRequest(Contract):
    artifact_id: Identifier
    config_version: NonNegativeInt
    request_id: Identifier


class TurnAttachment(Contract):
    type: Literal["work", "test"]
    id: str = Field(min_length=1)
    version: PositiveInt | None = None


class TurnRequest(Contract):
    role_id: Identifier
    text: str = Field(min_length=1, max_length=4000)
    request_id: Identifier
    task_id: str | None = Field(default=None, max_length=200)
    work_id: str | None = Field(default=None, max_length=200)
    attachments: list[TurnAttachment] | None = Field(default=None, max_length=10)


class FeedbackRequest(Contract):
    submission_id: Identifier
    retry: bool = False


class CodedHTTPException(HTTPException):
    def __init__(self, status_code, detail, code):
        super().__init__(status_code, detail)
        self.code = code


class ApprovalRequest(Contract):
    rule_id: Identifier
    request_id: Identifier
    expected_version: NonNegativeInt


class RelationRequest(Contract):
    claim: str = Field(min_length=1, max_length=4000)
    request_id: Identifier
    as_of_seq: NonNegativeInt | None = None


def create_app(database_url=None, scenario_path=None, model=None, study_path=None):
    store = SessionStore(database_url or os.getenv("CAREER_LAB_DATABASE_URL", "sqlite:///career_lab.db"))
    service = TrainingService(store)
    jobs = JobRepository(store.db)
    runtime = AgentRuntime(store, model or LocalModel())
    path = Path(scenario_path or "scenarios/pm_pilot/v1/scenario.yaml")
    app = FastAPI(title="Career Lab Backend", version="0.2.0")
    study_path = study_path or os.getenv("CAREER_LAB_STUDY")
    app.state.store, app.state.service, app.state.jobs, app.state.runtime = store, service, jobs, runtime
    from career_lab.api.feedback import generate_feedback, saved_feedback, read_evidence
    from career_lab.api.timeline import timeline
    app.state.handlers = {"turn": lambda p: runtime.run_turn(**p), "feedback": lambda p: generate_feedback(store, **p)}
    bearer = HTTPBearer(auto_error=False)

    def auth(session_id: str, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials:
            raise CodedHTTPException(401, "session token required", "token_required")
        try:
            valid = store.authenticate(session_id, credentials.credentials)
        except KeyError:
            valid = False
        if not valid:
            raise CodedHTTPException(401, "invalid session token", "token_invalid")
        return session_id

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        status = 409 if isinstance(exc, (VersionConflict, IdempotencyConflict)) else 422
        body = {"error": str(exc), "code": getattr(exc, "code", "invalid_request")}
        if getattr(exc, "details", None) is not None:
            body["details"] = exc.details
        return JSONResponse(body, status_code=status)

    @app.exception_handler(KeyError)
    async def missing(_, exc):
        return JSONResponse({"error": "not found", "code": "not_found"}, status_code=404)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_, exc):
        code = getattr(exc, "code", "not_found" if exc.status_code == 404 else "invalid_request")
        return JSONResponse({"detail": exc.detail, "code": code}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc):
        code = "query_length" if any(error["loc"] == ("body", "query") and error["type"] in
                                     {"string_too_short", "string_too_long"} for error in exc.errors()) else "invalid_request"
        return JSONResponse({"detail": jsonable_encoder(exc.errors()), "code": code}, status_code=422)

    @app.get("/health")
    def health():
        return {"status": "ok", "model": runtime.model.revision}

    @app.post("/sessions")
    def create(body: CreateSession):
        if body.scenario not in {"pm_pilot", "pm_pilot_urgent", "pm_pilot_capacity15"}:
            raise CodedValueError("unknown scenario", code="unknown_scenario")
        selected_path = path if body.scenario == "pm_pilot" else path.parents[2] / body.scenario / "v1/scenario.yaml"
        token = secrets.token_urlsafe(32)
        state = store.create_session(load_scenario(selected_path), token=token)
        return {"session_id": state.session_id, "token": token, "state": learner_state(store, state.session_id, state)}

    @app.get("/sessions/{session_id}")
    def session(session_id=Depends(auth)):
        return {"state": learner_state(store, session_id)}

    @app.get("/sessions/{session_id}/materials")
    def materials(session_id=Depends(auth), as_of_seq: int | None = None):
        return [m.model_dump(mode="json") for m in store.project_view(session_id, "learner", as_of_seq).permitted_materials]

    @app.post("/sessions/{session_id}/actions")
    def action(body: ActionRequest, session_id=Depends(auth)):
        result = service.action(session_id, **body.model_dump())
        return {**result.model_dump(mode="json"), "state": learner_state(store, session_id, result.state),
                "snapshots": [learner_state(store, session_id, state) for state in result.snapshots]}

    @app.post("/sessions/{session_id}/tests")
    def test(body: TestRequest, session_id=Depends(auth)):
        return object_response(store, session_id, service.run_assistant_test(session_id, **body.model_dump()))

    @app.get("/sessions/{session_id}/tests")
    def tests(session_id=Depends(auth)):
        return object_list(store, session_id, "test")

    @app.post("/sessions/{session_id}/relation-checks")
    def relation_check(body: RelationRequest, session_id=Depends(auth)):
        if not study_path:
            raise CodedHTTPException(503, "frozen relation study is not configured", "relation_not_configured")
        from career_lab.api.relation import shadow_check
        return shadow_check(store, study_path, session_id, **body.model_dump())

    @app.post("/sessions/{session_id}/approvals/resolve")
    def approval(body: ApprovalRequest, session_id=Depends(auth)):
        from career_lab.api.approvals import resolve_approval
        return resolve_approval(store, session_id, **body.model_dump())

    @app.post("/sessions/{session_id}/artifacts")
    def artifact(body: ArtifactRequest, session_id=Depends(auth)):
        return object_response(store, session_id, service.save_artifact(session_id, body.content.model_dump(), body.request_id))

    @app.get("/sessions/{session_id}/artifacts")
    def artifacts(session_id=Depends(auth)):
        return object_list(store, session_id, "artifact")

    @app.post("/sessions/{session_id}/submissions")
    def submit(body: SubmitRequest, session_id=Depends(auth)):
        return object_response(store, session_id, service.submit_plan(session_id, **body.model_dump()))

    @app.get("/sessions/{session_id}/submissions")
    def submissions(session_id=Depends(auth)):
        return object_list(store, session_id, "submission")

    @app.post("/sessions/{session_id}/turns")
    def turn(body: TurnRequest, session_id=Depends(auth)):
        if body.role_id not in {role.id for role in store.get_spec(session_id).roles}:
            raise CodedValueError("unknown role", code="unknown_role")
        state = store.get_state(session_id)
        if state.status != "active":
            raise InvalidAction(f"session is {state.status}", code=f"session_{state.status}")
        payload = {"session_id": session_id, **body.model_dump(exclude_none=True)}
        return {"job_id": jobs.enqueue(f"{session_id}:turn:{body.request_id}", "turn", payload)}

    @app.get("/sessions/{session_id}/jobs/{job_id}")
    def job(job_id: str, session_id=Depends(auth)):
        result = jobs.get(job_id)
        if result["payload"].get("session_id") != session_id:
            raise KeyError("job not found")
        return {**{k: result[k] for k in ("id", "status", "attempt", "result", "error", "kind", "queued_at", "started_at", "finished_at")},
                "role_id": result["payload"].get("role_id") if result["kind"] == "turn" else None}

    @app.post("/sessions/{session_id}/feedback")
    def feedback(body: FeedbackRequest, session_id=Depends(auth)):
        sub = store.get_object(session_id, body.submission_id, "submission")
        payload = {"session_id": session_id, "submission_id": body.submission_id}
        job_id = jobs.enqueue(f"{session_id}:feedback:{body.submission_id}:{sub['model_revision']}", "feedback", payload)
        if body.retry:
            jobs.retry_failed(job_id)
        return {"job_id": job_id}

    @app.get("/sessions/{session_id}/feedback/{submission_id}")
    def feedback_result(submission_id: str, session_id=Depends(auth)):
        return saved_feedback(store, session_id, submission_id)

    @app.get("/sessions/{session_id}/timeline")
    def replay(session_id=Depends(auth)):
        return timeline(store, session_id)

    @app.get("/sessions/{session_id}/evidence/{submission_id}/{criterion_id}/{evidence_id}")
    def evidence(submission_id: str, criterion_id: str, evidence_id: str, session_id=Depends(auth)):
        return read_evidence(store, session_id, submission_id, criterion_id, evidence_id)

    return app
