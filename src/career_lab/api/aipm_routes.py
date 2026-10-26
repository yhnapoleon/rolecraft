"""Runtime extension routes; keep the frozen OpenAPI and business tools unchanged."""

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from career_lab.contracts import v2 as C

READS = (
    ("/guide", "aipm.guide.read"),
    ("/progress", "aipm.progress.read"),
    ("/process-feedback", "aipm.process_feedback.read"),
    ("/submissions/{submission_id}/versions/{version}/feedback", "aipm.submission_feedback.read"),
    ("/designs/{design_id}", "aipm.design.read"),
    ("/batches/{batch_id}", "aipm.batch.read"),
    ("/drafts", "aipm.design_drafts.list"),
    ("/section-reviews", "aipm.section_review.read"),
)
WRITES = (
    ("/enrollment", "aipm.enroll"),
    ("/focus", "aipm.focus.set"),
    ("/step-links", "aipm.step_links.save"),
    ("/designs", "aipm.design.save"),
    ("/batches", "aipm.batch.create"),
    ("/batches/{batch_id}/state", "aipm.batch.update"),
    ("/assessments", "aipm.assessment.record"),
    ("/drafts", "aipm.design.draft"),
    ("/drafts/{draft_id}/state", "aipm.design_drafts.resolve"),
    ("/section-reviews", "aipm.section_review.create"),
)
# The only extension write a delegated Agent may make: a draft awaiting the owner.
AGENT_WRITES = frozenset({"aipm.design.draft"})


def mount_aipm_routes(app):
    if getattr(app.state, "aipm_routes_mounted", False):
        return
    bearer = HTTPBearer(auto_error=False)
    credential_dependency = Depends(bearer)
    gateway, store = app.state.gateway, app.state.v2_store

    def authenticate(session_id, credentials):
        if credentials is None:
            raise C.ProtocolError("token_required", status=401)
        return store.authenticate(session_id, credentials.credentials)

    def read_endpoint(operation):
        def endpoint(
            request: Request,
            session_id: str,
            credentials: HTTPAuthorizationCredentials | None = credential_dependency,
        ):
            auth = authenticate(session_id, credentials)
            params = dict(request.query_params)
            params.update({k: v for k, v in request.path_params.items() if k != "session_id"})
            return gateway.dispatch(auth, operation, params)

        return endpoint

    def write_endpoint(operation):
        def endpoint(
            request: Request,
            session_id: str,
            body: C.Command,
            credentials: HTTPAuthorizationCredentials | None = credential_dependency,
        ):
            auth = authenticate(session_id, credentials)
            human = auth.executor.kind == "human" and auth.actor_id == "learner"
            agent = auth.executor.kind == "external_agent" and operation in AGENT_WRITES
            if not (human or agent):
                raise C.ProtocolError("human_required", status=403)
            params = {k: v for k, v in request.path_params.items() if k != "session_id"}
            command = body.model_dump(mode="json")
            # Read-only preparation outside the write transaction (e.g. rule checks).
            prepare = getattr(app.state, "aipm_prepare", {}).get(operation)
            if prepare is None:
                return gateway.dispatch(auth, operation, command, params)
            with prepare(auth, command):
                return gateway.dispatch(auth, operation, command, params)

        return endpoint

    for method, routes, factory in [
        ("GET", READS, read_endpoint),
        ("POST", WRITES, write_endpoint),
    ]:
        for suffix, operation in routes:
            app.add_api_route(
                "/sessions/{session_id}/aipm" + suffix,
                factory(operation),
                methods=[method],
                include_in_schema=False,
                name=operation,
            )
    app.state.aipm_routes_mounted = True
