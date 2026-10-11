"""Private preview annotations over the existing exact-version review evaluator."""

from typing import TYPE_CHECKING, TypedDict

from career_lab.api.reviews_v2 import create_review_evaluator, prepare_review_feedback
from career_lab.contracts import v2 as C
from career_lab.contracts.v2.evaluation import _OutcomeAction as OutcomeAction
from career_lab.contracts.v2.evaluation import _OutcomeItem as OutcomeItem
from career_lab.contracts.v2.evaluation import _PreviewConditions as PreviewConditions
from career_lab.evidence.v2.assembler import purpose_of
from career_lab.evidence.v2.localization import message
from career_lab.evidence.v2.store_reader import StoreEvidenceReader
from career_lab.scenarios.v2.policy import effective_config

if TYPE_CHECKING:
    from career_lab.api.evaluation_runtime import ScenarioEvidencePort


class SavedCheck(TypedDict):
    outcomes: tuple[OutcomeItem, ...]
    missing: tuple[str, ...]
    questions: tuple[str, ...]
    operations: tuple[str, ...]
    business: bool


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
                "preview_conditions": recorded_conditions(source, request, auth),
            }
        )
        for report in prepared["reports"]
    )
    return prepared


def recorded_conditions(
    source: "ScenarioEvidencePort", request: C.ReviewRequest, auth: C.AuthContext
) -> PreviewConditions | None:
    """Key conditions at the request point, so later reads can name what changed."""
    try:
        snapshot = source.window(auth, request.as_of).snapshot
    except C.ProtocolError:
        return None
    # Only materials the requester may open, as in the requester's own material list.
    visible = source.module.package.visible_materials(
        snapshot.source_versions, auth.actor_id, snapshot.world.business_seq, auth.session_id
    )
    return PreviewConditions(
        config_version=snapshot.world.config_version,
        resources=dict(snapshot.world.resources),
        source_versions={material.id: material.version for material, _ in visible},
    )


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
                summary=message(language, "尚未声明决定，可以继续探索。"),
                missing_inputs=("decision",),
            )
        )
    for index, name in enumerate(request.requested_outcomes or ()):
        if name not in {"saved_input", "decision", "configuration"}:
            outcomes.append(
                OutcomeItem(
                    id="unsupported-" + str(index + 1),
                    kind="unsupported",
                    summary=message(language, "当前场景未建模此结果；原始请求已保留。"),
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
            summary=message(language, "候选配置或资源依据尚未核实。"),
        )
    return OutcomeItem(
        id="configuration",
        kind="conditional_prediction",
        basis_refs=tuple(proofs),
        summary=message(language, "若明确应用此候选方案，其生效配置将受当前已记录资源约束。"),
        conditions=(
            message(language, "已记录资源与基础配置保持不变。"),
            message(language, "仍需明确的授权动作；此预览未批准或执行。"),
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
        summary=message(language, "已核实保存的作品版本（规则核实）。"),
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


CLARIFICATION_QUESTIONS = {
    "purpose": "希望用这份作品判断什么？",
    "candidate_config": "希望核对哪份候选配置？",
    "authorized_basis": "请补充可访问的资源和配置依据。",
}


def clarification_questions(missing: tuple[str, ...], language: str) -> tuple[str, ...]:
    return tuple(message(language, CLARIFICATION_QUESTIONS[key]) for key in missing)


def pending_configuration(missing: tuple[str, ...], language: str) -> OutcomeItem:
    return OutcomeItem(
        id="configuration",
        kind="pending_verification",
        missing_inputs=missing,
        summary=message(language, "候选条件仍需澄清。"),
    )


# Purposes whose outcome depends on the live configuration, resources and source materials.
BUSINESS_PURPOSES = frozenset({"plan", "option", "commitment", "result"})
# Existing tools each purpose leads to; a preview links to them and never runs them.
PURPOSE_OPERATIONS = {
    "plan": ("tests.create", "configuration.apply"),
    "option": ("configuration.apply",),
    "commitment": ("submissions.create", "actions", "configuration.apply"),
    "result": ("submissions.create",),
}
TASK_QUESTIONS = {
    "plan": "这份测试计划要支持哪件事？",
    "option": "这次方案比较是为哪件事做的？",
    "commitment": "这项试点决定针对哪件事？",
    "result": "这份结果报告对应哪件事？",
}
TASK_SPECIFIC_QUESTIONS = {
    "test_cases": "「{task}」要在测试台上运行哪些问题？",
    "candidate_config": "「{task}」要核对哪份候选配置？",
    "decision_evidence": "「{task}」的决定依据哪些资料或测试结果？",
    "result_evidence": "「{task}」的结果引用了哪些测试运行？",
}


def saved_version_check(
    product: C.WorkProductVersion,
    task_title: str | None,
    proof: C.EvidenceRefV2,
    config: C.EvidenceRefV2 | None,
    language: str,
) -> SavedCheck:
    """Rules-only outcome of one saved version, chosen by its purpose and task.

    Only what is missing for this purpose is asked, one short question at a time; a note that
    needs nothing has no question. Free text is never classified and nothing is executed.
    """
    purpose = purpose_of(product.purpose) if product.purpose.strip() else None
    business = purpose in BUSINESS_PURPOSES
    missing = saved_version_missing(product, purpose)
    outcomes = [saved_input_outcome(proof, proof, 1, language)]
    if not product.purpose.strip():
        outcomes.append(
            OutcomeItem(
                id="purpose",
                kind="pending_verification",
                summary=message(language, "用途未说明，暂不判断业务结果。"),
                missing_inputs=("purpose",),
            )
        )
    elif purpose == "plan":
        if config is not None:
            outcomes.append(
                OutcomeItem(
                    id="test-run",
                    kind="conditional_prediction",
                    summary=message(
                        language,
                        "若在测试台明确运行，这些问题将按第 {config} 版配置和当前资料版本回答。",
                        config=config.config_version,
                    ),
                    basis_refs=(proof, config),
                    conditions=(
                        message(language, "运行前配置与资料版本保持不变。"),
                        message(language, "需要你在测试台明确运行；此预览未运行测试。"),
                    ),
                    values={"config_version": config.config_version},
                )
            )
        outcomes.append(
            OutcomeItem(
                id="test-results",
                kind="pending_verification",
                summary=message(language, "回答是否符合预期要实际运行后才能核实。"),
                missing_inputs=("test_run",),
            )
        )
    elif purpose == "option":
        outcomes.append(pending_configuration(("candidate_config",), language))
    elif purpose in {"commitment", "result"}:
        if config is not None:
            outcomes.append(
                OutcomeItem(
                    id="submission",
                    kind="conditional_prediction",
                    summary=message(
                        language,
                        "若明确提交，交付将固定这份作品第 {version} 版和第 {config} 版配置。",
                        version=product.version,
                        config=config.config_version,
                    ),
                    basis_refs=(proof, config),
                    conditions=(
                        message(language, "提交前作品与配置保持不变。"),
                        message(language, "需要你明确提交；此预览未提交，也未申请审批。"),
                    ),
                    values={"version": product.version, "config_version": config.config_version},
                )
            )
        outcomes.append(
            OutcomeItem(
                id="acceptance",
                kind="pending_verification",
                summary=message(language, "经理是否接受、业务是否达成要在提交和评审后才能知道。"),
                missing_inputs=("submission_review",),
            )
        )
    return {
        "outcomes": tuple(outcomes),
        "missing": missing,
        "questions": saved_version_questions(missing[:1], purpose, task_title, language),
        "operations": ("reviews.create", "work_products.shares.create")
        + PURPOSE_OPERATIONS.get(purpose or "", ()),
        "business": business,
    }


def saved_version_missing(product: C.WorkProductVersion, purpose: str | None) -> tuple[str, ...]:
    """Ordered structural gaps for this purpose; the text itself is not classified."""
    if not product.purpose.strip():
        return ("purpose",)
    if purpose not in BUSINESS_PURPOSES:
        return ()
    missing = [] if product.task is not None else ["task"]
    payload = product.structured_payload
    if purpose == "plan" and payload is not None and payload.type == "test_plan":
        missing += [] if payload.cases else ["test_cases"]
    elif purpose == "option":
        missing.append("candidate_config")
    elif purpose == "commitment" and not product.evidence_refs:
        missing.append("decision_evidence")
    elif purpose == "result" and not product.evidence_refs:
        missing.append("result_evidence")
    return tuple(missing)


def saved_version_questions(
    missing: tuple[str, ...], purpose: str | None, task_title: str | None, language: str
) -> tuple[str, ...]:
    questions = []
    for key in missing:
        if key == "purpose":
            questions.append(message(language, CLARIFICATION_QUESTIONS["purpose"]))
        elif key == "task":
            questions.append(message(language, TASK_QUESTIONS[purpose or ""]))
        else:
            task = task_title or message(language, "这件事")
            questions.append(message(language, TASK_SPECIFIC_QUESTIONS[key], task=task))
    return tuple(questions)
