"""Post-Gateway installation. Both the registry and the actual store need models."""

from career_lab.api.aipm_routes import mount_aipm_routes
from career_lab.api.modules import Operation, V2Response
from career_lab.contracts import v2 as C

from .feedback_discovery import discover
from .types import FeedbackRead


def install_aipm(app):
    if getattr(app.state, "aipm_installed", False):
        return
    registry = app.state.gateway.registry

    def feedback(view, query, auth):
        ref = C.ObjectRef(
            session_id=auth.session_id,
            kind="submission",
            object_id=query.submission_id,
            version=query.version,
        )
        return V2Response(result=discover(view, auth, ref, registry).model_dump(mode="json"))

    registry.register(
        Operation(
            "aipm.submission_feedback.read",
            "read",
            FeedbackRead,
            feedback,
            mutates=False,
            response_model=V2Response,
            action_name="submissions.list",
        )
    )
    mount_aipm_routes(app)
    app.state.aipm_installed = True
