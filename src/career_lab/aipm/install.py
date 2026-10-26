"""Post-Gateway installation. Both the registry and the actual store need models."""

from contextlib import contextmanager

from career_lab.aipm.design import OBJECT_MODELS as DESIGN_MODELS
from career_lab.aipm.design import operations as design_operations
from career_lab.aipm.design.handlers import DesignReadInput, DesignSaveInput
from career_lab.aipm.evaluation.service import OBJECT_MODELS as EVALUATION_MODELS
from career_lab.aipm.evaluation.service import EvaluationService
from career_lab.api.aipm_routes import mount_aipm_routes
from career_lab.api.modules import Operation, V2Response
from career_lab.contracts import v2 as C

from . import review
from .drafts import handlers as draft_handlers
from .feedback_discovery import discover
from .progress import default_contents, design_facts, enrolled, handlers, require_owner
from .review_model import ModelReviewer
from .types import (
    AipmDesignDraft,
    AipmFocus,
    AipmProfile,
    AipmStepLink,
    DraftInput,
    DraftList,
    DraftResolve,
    EmptyRead,
    EnrollInput,
    FeedbackRead,
    FocusInput,
    PageRead,
    SectionReview,
    SectionReviewInput,
    SectionReviewRead,
    StepLinkInput,
)

OBJECT_MODELS = {
    "aipm_profile": AipmProfile,
    "aipm_focus": AipmFocus,
    "aipm_step_link": AipmStepLink,
    "aipm_design_draft": AipmDesignDraft,
    "aipm_section_review": SectionReview,
    **DESIGN_MODELS,
    **EVALUATION_MODELS,
}


def register_models(registry, store):
    for kind, model in OBJECT_MODELS.items():
        if registry.object_models.get(kind) is not model:
            registry.register_object_model(kind, model)
        if store.object_models.get(kind) is not model:
            store.register_object(kind, model)


def add_contents(app, contents):
    """Bind installed content by exact scenario hash; a hash never changes meaning."""
    catalog = app.state.aipm_catalog
    for content in contents:
        known = catalog.get(content.scenario_hash)
        if known is not None and known != content:
            raise ValueError("aipm content already bound to this scenario hash")
        catalog[content.scenario_hash] = content


def _read(name, model, handler, action):
    def wrapped(view, query, auth):
        return V2Response(result=handler(view, query, auth))

    return Operation(
        name, "read", model, wrapped, mutates=False, response_model=V2Response, action_name=action
    )


def install_aipm(app, contents=None):
    if getattr(app.state, "aipm_installed", False):
        if contents:
            add_contents(app, contents)
        return
    registry = app.state.gateway.registry
    app.state.aipm_catalog = {}
    add_contents(app, default_contents() if contents is None else contents)
    catalog = app.state.aipm_catalog
    register_models(registry, app.state.v2_store)

    def feedback(view, query, auth):
        ref = C.ObjectRef(
            session_id=auth.session_id,
            kind="submission",
            object_id=query.submission_id,
            version=query.version,
        )
        return discover(view, auth, ref, registry).model_dump(mode="json")

    own = handlers(catalog, registry)
    for name, model, action in (
        ("aipm.guide.read", EmptyRead, "observation"),
        ("aipm.progress.read", EmptyRead, "observation"),
        ("aipm.process_feedback.read", PageRead, "observation"),
    ):
        registry.register(_read(name, model, own[name], action))
    registry.register(
        _read("aipm.submission_feedback.read", FeedbackRead, feedback, "submissions.list")
    )
    for name, model in (
        ("aipm.enroll", EnrollInput),
        ("aipm.focus.set", FocusInput),
        ("aipm.step_links.save", StepLinkInput),
    ):
        registry.register(Operation(name, "act", model, own[name]))

    drafts = draft_handlers(catalog, registry)
    registry.register(
        Operation("aipm.design.draft", "act", DraftInput, drafts["aipm.design.draft"])
    )
    registry.register(
        Operation(
            "aipm.design_drafts.resolve",
            "act",
            DraftResolve,
            drafts["aipm.design_drafts.resolve"],
        )
    )
    registry.register(
        _read(
            "aipm.design_drafts.list", DraftList, drafts["aipm.design_drafts.list"], "observation"
        )
    )

    store = app.state.v2_store

    def review_create(view, command, auth):
        require_owner(auth)
        content = enrolled(view, auth, catalog)
        if view.state.status == "submitted":
            raise C.ProtocolError("session_submitted", status=409)
        body = SectionReviewInput.model_validate(command.payload)
        model = "running" if reviewer.configured() else "not_configured"
        return review.create(view, auth, content, body, review.RULE_CHECK.get(), model)

    def review_read(view, query, auth):
        enrolled(view, auth, catalog)
        page = review.page(view, auth, query.step_id, query.cursor, query.limit)
        for item in page["items"]:
            stored = item["review"]
            if stored.get("model_status") == "running" and not reviewer.in_flight(stored["id"]):
                # Interrupted (e.g. a restart). Asking for the same review again resumes it.
                item["review"] = dict(
                    stored,
                    model_status="failed",
                    model_reason=reviewer.interrupted(content_of(view)),
                )
        return V2Response(result=page)

    def content_of(view):
        return catalog[view.bindings.scenario.sha256]

    reviewer = ModelReviewer(app, catalog)
    app.state.aipm_reviewer = reviewer

    def start_model(auth, result):
        body = (result or {}).get("result") or {}
        stored = body.get("review") or {}
        if stored.get("model_status") == "running":
            reviewer.start(auth, C.ObjectRef.model_validate(body["ref"]))

    @contextmanager
    def prepare_review(auth, command):
        """Run the existing read-only rule check before the write transaction opens."""
        token = review.RULE_CHECK.set(rule_check_for(auth, command))
        try:
            yield
        finally:
            review.RULE_CHECK.reset(token)

    def rule_check_for(auth, command):
        require_owner(auth)
        body = SectionReviewInput.model_validate(command.get("payload") or {})
        if body.design_ref is None:
            return None
        design = store.query(auth, lambda view: view.get(body.design_ref).content)
        decision = design.get("intended_decision")
        bindings, _ = store.session_metadata(auth)
        checks = getattr(registry, "rule_checks", {}).get(C.canonical(bindings))
        if decision is None or checks is None:
            return None
        request = C.SubmissionRuleCheckRequest(
            schema_version=2,
            request_id=command["request_id"],
            expected_version=command["expected_version"],
            expected_workspace_revision=command["expected_workspace_revision"],
            operation="submissions.rule_check",
            payload=C.SubmitInput(decision=decision, products=(body.prd_ref,)),
        )
        return checks.draft(store, auth, request)

    registry.register(
        Operation("aipm.section_review.create", "act", SectionReviewInput, review_create)
    )
    registry.register(
        Operation(
            "aipm.section_review.read",
            "read",
            SectionReviewRead,
            review_read,
            mutates=False,
            response_model=V2Response,
            action_name="observation",
        )
    )
    app.state.aipm_prepare = {"aipm.section_review.create": prepare_review}
    app.state.aipm_after = {"aipm.section_review.create": start_model}

    # L2 rules come from the enrolled package only; one operation set per rules file.
    built = {}

    def design_op(view, auth, name):
        content = enrolled(view, auth, catalog)
        if content.design_rules is None:
            raise C.ProtocolError("aipm_design_rules_unavailable", status=503)
        key = (content.scenario_hash, content.design_rules)
        if key not in built:
            ops = design_operations(
                rules_path=content.design_rules, facts_provider=design_facts(content)
            )
            built[key] = {op.name: op.handler for op in ops}
        return built[key][name]

    registry.register(
        Operation(
            "aipm.design.save",
            "act",
            DesignSaveInput,
            lambda view, command, auth: design_op(view, auth, "aipm.design.save")(
                view, command, auth
            ),
        )
    )
    registry.register(
        Operation(
            "aipm.design.read",
            "read",
            DesignReadInput,
            lambda view, query, auth: design_op(view, auth, "aipm.design.read")(view, query, auth),
            mutates=False,
            response_model=V2Response,
            action_name="objects.read",
        )
    )
    # L3 handlers; request lookup is the Gateway's read-only authorized result reader.
    for op in EvaluationService(app.state.gateway.request_result).operations():
        registry.register(op)
    mount_aipm_routes(app)
    app.state.aipm_installed = True
