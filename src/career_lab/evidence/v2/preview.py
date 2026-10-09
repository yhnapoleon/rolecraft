"""Private preview annotations over the existing exact-version review evaluator."""

from typing import TYPE_CHECKING, TypedDict

from career_lab.api.reviews_v2 import create_review_evaluator, prepare_review_feedback
from career_lab.contracts import v2 as C
from career_lab.contracts.v2.evaluation import _OutcomeAction as OutcomeAction
from career_lab.contracts.v2.evaluation import _OutcomeItem as OutcomeItem
from career_lab.evidence.v2.store_reader import StoreEvidenceReader
from career_lab.scenarios.v2.policy import effective_config

if TYPE_CHECKING:
    from career_lab.api.evaluation_runtime import ScenarioEvidencePort


class PreparedPreview(TypedDict):
    request: C.ReviewRequest
    request_hash: str
    reports: tuple[C.FeedbackV2, ...]
    work_language: str
    followup_of: tuple[C.ObjectRef, ...]
    followup_status: str | None
    followup_evidence_status: str | None


def prepare_preview_feedback(
    reader: StoreEvidenceReader,
    request: C.ReviewRequest,
    auth: C.AuthContext,
    language: str,
    source: "ScenarioEvidencePort",
) -> PreparedPreview:
    prepared = prepare_review_feedback(
        create_review_evaluator(reader, work_language=language), auth, request
    )
    configuration = configuration_outcome(source, request, auth, language)
    outcomes = (*input_outcomes(reader, request, auth, language), configuration)
    missing = tuple(dict.fromkeys(configuration.missing_inputs))
    questions = clarification_questions(missing, language)
    basis = tuple(
        {
            C.canonical(ref): C.ObjectRef.model_validate(
                ref.model_dump(include=set(C.ObjectRef.model_fields))
            )
            for item in outcomes
            for ref in item.basis_refs
        }.values()
    )
    actions = tuple(
        OutcomeAction(operation=name, objects=request.subjects)
        for name in request.available_operations or ()
        if name in {"reviews.create", "work_products.shares.create"}
    )
    if configuration.kind == "conditional_prediction":
        actions += tuple(
            OutcomeAction(operation=name, objects=basis)
            for name in request.available_operations or ()
            if name in {"configuration.apply", "tests.create"}
        )
    prepared["reports"] = tuple(
        report.model_copy(
            update={
                "preview_kind": request.preview_kind,
                "preview_language": language,
                "outcomes": outcomes,
                "basis_refs": basis,
                "conditions": configuration.conditions,
                "available_actions": actions,
                "input_refs": request.subjects,
                "evaluation_as_of": request.as_of,
                "missing_inputs": missing,
                "clarification": questions,
                "generation_status": "waiting_model",
            }
        )
        for report in prepared["reports"]
    )
    return prepared


def input_outcomes(
    reader: StoreEvidenceReader, request: C.ReviewRequest, auth: C.AuthContext, language: str
) -> tuple[OutcomeItem, ...]:
    outcomes = []
    for index, subject in enumerate(request.subjects):
        source = reader.read(auth, subject, request.as_of)
        outcomes.append(saved_input_outcome(subject, source.ref, index + 1, language))
    if request.decision is None:
        outcomes.append(
            OutcomeItem(
                id="decision",
                kind="pending_verification",
                summary="No decision has been declared; you can continue exploring."
                if language == "en"
                else "尚未声明决定，可以继续探索。",
                missing_inputs=("decision",),
            )
        )
    for index, name in enumerate(request.requested_outcomes or ()):
        if name not in {"saved_input", "decision", "configuration"}:
            outcomes.append(
                OutcomeItem(
                    id="unsupported-" + str(index + 1),
                    kind="unsupported",
                    summary="This outcome is not modeled. Your original request is retained."
                    if language == "en"
                    else "当前场景未建模此结果；原始请求已保留。",
                    values={"requested_outcome": name},
                )
            )
    return tuple(outcomes)


def configuration_outcome(
    source: "ScenarioEvidencePort", request: C.ReviewRequest, auth: C.AuthContext, language: str
) -> OutcomeItem:
    missing = configuration_missing(request.purpose, request.candidate_config)
    if missing:
        return pending_configuration(missing, language)
    try:
        window = source.window(auth, request.as_of)
        current = window.snapshot.config
        config_ref = C.ObjectRef(
            session_id=auth.session_id,
            kind="config",
            object_id=current.id,
            version=current.version,
            config_version=current.config_version,
        )
        proofs = [source.source(auth, config_ref, request.as_of).ref]
        for name in ("brief", "technical"):
            ref = C.ObjectRef(
                session_id=auth.session_id, kind="material", object_id=name, version=1
            )
            proofs.append(source.source(auth, ref, request.as_of).ref)
        resources = dict(source.module.package.bundle.initial_resources)
        for row in sorted(window.objects, key=lambda row: row.created_storage_revision):
            if row.ref.kind == "business_decision" and row.content["status"] in {
                "approved",
                "accepted",
            }:
                proofs.append(source.source(auth, row.ref, request.as_of).ref)
                resources.update(row.content["granted"])
        if resources != dict(window.snapshot.world.resources):
            raise C.ProtocolError("resource_basis_unavailable")
        candidate = request.candidate_config
        assert candidate is not None
        checked = effective_config(source.module.package, candidate, resources)
    except (C.ProtocolError, KeyError):
        return OutcomeItem(
            id="configuration",
            kind="pending_verification",
            missing_inputs=("authorized_basis",),
            summary="Candidate configuration or resource evidence could not be verified."
            if language == "en"
            else "候选配置或资源依据尚未核实。",
        )
    return OutcomeItem(
        id="configuration",
        kind="conditional_prediction",
        basis_refs=tuple(proofs),
        summary="If applied, this candidate is constrained by the recorded allocation."
        if language == "en"
        else "若明确应用此候选方案，其生效配置将受当前已记录资源约束。",
        conditions=(
            "The recorded resource allocation and base configuration remain unchanged."
            if language == "en"
            else "已记录资源与基础配置保持不变。",
            "Explicit action is still required. This preview has not approved or executed anything."
            if language == "en"
            else "仍需明确的授权动作；此预览未批准或执行。",
        ),
        values={
            "requested": candidate.model_dump(mode="json"),
            "effective": checked.effective.model_dump(mode="json"),
            "differences": dict(checked.differences),
        },
    )


def saved_input_outcome(
    subject: C.ObjectRef, proof: C.EvidenceRefV2, index: int, language: str
) -> OutcomeItem:
    return OutcomeItem(
        id="saved-input-" + str(index),
        kind="fact",
        summary="Saved version verified (rule checked)."
        if language == "en"
        else "已核实保存的作品版本（规则核实）。",
        basis_refs=(proof,),
        values={"version": subject.version},
    )


def configuration_missing(purpose: str, candidate: C.AssistantConfig | None) -> tuple[str, ...]:
    # Numerical feasibility does not require classifying free-text business intent.
    missing = []
    if not purpose.strip():
        missing.append("purpose")
    if candidate is None:
        missing.append("candidate_config")
    return tuple(missing)


def clarification_questions(missing: tuple[str, ...], language: str) -> tuple[str, ...]:
    questions = {
        "purpose": ("希望用这份作品判断什么？", "What would you like to evaluate this work for?"),
        "candidate_config": (
            "希望核对哪份候选配置？",
            "Which candidate configuration should be checked?",
        ),
        "authorized_basis": (
            "请补充可访问的资源和配置依据。",
            "Provide accessible resource and configuration evidence.",
        ),
    }
    return tuple(questions[key][int(language == "en")] for key in missing)


def pending_configuration(missing: tuple[str, ...], language: str) -> OutcomeItem:
    return OutcomeItem(
        id="configuration",
        kind="pending_verification",
        missing_inputs=missing,
        summary="Candidate conditions need clarification."
        if language == "en"
        else "候选条件仍需澄清。",
    )
