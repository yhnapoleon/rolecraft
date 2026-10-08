"""Read-only review handlers: local source gaps do not erase other feedback.

Public DTOs, persisted identities, worker registration and objections remain W01
contracts. This owned boundary returns separately timed, inspectable sections.
"""

from career_lab.contracts.v2.core import ProtocolError
from career_lab.contracts import v2 as C
from .formal_feedback import attach_sections
from .assembler import EvidenceAssemblerV2, base_ref, purpose_of
from .factual import factual_feedback
from .history import before
from .localization import message, validate_language
from .availability import unavailable, SAFE_REASON

UNSET = object()
DECISIONS = frozenset({"launch", "launch_narrow", "no_go", "defer_with_conditions"})


class ReviewEvaluator:
    def __init__(self, reader, *, engine=None, model_bytes=16000, work_language="zh"):
        from career_lab.rubrics.v4.feedback import FeedbackEngine

        self.work_language = validate_language(work_language)
        self.reader = reader
        self.engine = engine or FeedbackEngine()
        self.model_bytes = model_bytes

    def _decision(self, auth, subject, source, at, explicit):
        if explicit is not UNSET:
            if explicit is not None and explicit not in DECISIONS:
                raise ProtocolError("invalid_decision")
            return explicit, "explicit_request" if explicit is not None else "unspecified"
        declared = source.structured_decision
        if declared is None:
            return None, "unspecified"
        if (
            declared.value not in DECISIONS
            or declared.subject != subject
            or declared.declared_at != at
            or base_ref(declared.source) != subject
        ):
            raise ProtocolError("structured_decision_binding_mismatch")
        try:
            EvidenceAssemblerV2(self.reader).resolve(auth, declared.source, at)
        except (KeyError, ProtocolError) as error:
            if not unavailable(error):
                raise
            return None, "structured_unverified"
        return declared.value, "structured_subject"

    def review(
        self, auth, subjects, *, purpose, requested_at, decision=UNSET, scope=(), question=""
    ):
        work_language = self.work_language
        policies = self.reader.policies()
        if set(scope) - {p.id for p in policies}:
            raise ProtocolError("unknown_review_scope")
        selected = tuple(p for p in policies if not scope or p.id in scope)
        if (
            not subjects
            or len(subjects) > 50
            or len(subjects) != len({r.model_dump_json() for r in subjects})
        ):
            raise ProtocolError("invalid_review_subjects")
        results = []
        for subject in subjects:
            if subject.kind != "product":
                raise ProtocolError("unsupported_review_subject")
            # Session/subject access errors are intentionally not caught.
            source = self.reader.read(auth, subject, requested_at)
            if base_ref(source.ref) != subject:
                raise ProtocolError("subject_identity_mismatch")
            at = source.created_at
            if at is None:
                facts = {
                    "section": "verified_facts",
                    "status": "unknown",
                    "as_of": None,
                    "summary": [
                        message(work_language, "作品形成时点未知，未用请求时点补造历史判断。")
                    ],
                }
                items = tuple(
                    C.FeedbackItem(
                        criterion=p.id,
                        label="INSUFFICIENT",
                        applicability="undetermined",
                        source="pending",
                        explanation=message(work_language, "作品形成时点未知，历史责任待核验。"),
                        citations=(),
                    )
                    for p in selected
                )
                report = C.FeedbackV2(
                    id=C.digest(
                        [
                            subject.model_dump(mode="json"),
                            self.reader.evaluation.model_dump(mode="json"),
                            "unknown-subject-time",
                        ]
                    ),
                    session_id=auth.session_id,
                    subject=subject,
                    evaluation=self.reader.evaluation,
                    as_of=requested_at,
                    items=items,
                    business_response=message(work_language, "未核对业务决定。"),
                    next_options=(
                        message(work_language, "补全可信形成时点后重新评审，原作品保留。"),
                    ),
                    verified_coverage=0,
                    model_coverage=0,
                )
                report = attach_sections(
                    report,
                    self.reader,
                    auth,
                    subject,
                    requested_at,
                    facts,
                    [],
                    [i.model_dump(mode="json") for i in items],
                    work_language=work_language,
                )
                results.append(
                    {
                        "subject": subject.model_dump(mode="json"),
                        "evaluated_at": None,
                        "requested_at": requested_at.model_dump(mode="json"),
                        "verified_facts": facts,
                        "historical_responsibilities": [],
                        "feedback": report.model_dump(mode="json"),
                        "pending_reason": "subject_point_unknown",
                    }
                )
                continue
            if not before(at, requested_at):
                raise ProtocolError("future_subject_anchor")
            chosen, origin = self._decision(auth, subject, source, at, decision)
            facts = factual_feedback(
                self.reader, auth, subject, at, requested_at, work_language=work_language
            )
            reference_gap = any(
                r["status"] != "exact_reference_verified" for r in facts["references"]
            )
            snapshot = self.reader.snapshot(auth, subject, at)
            assembler = EvidenceAssemblerV2(
                self.reader, self.model_bytes, work_language=work_language
            )
            packages = tuple(
                assembler.assemble(
                    auth=auth,
                    subject_id=subject.object_id,
                    subjects=(subject,),
                    evidence_refs=source.declared_refs,
                    purpose=purpose,
                    decision=chosen,
                    as_of=at,
                    policy=policy,
                    snapshot=snapshot,
                    question=question,
                    anchor_mode="product_version",
                    requested_at=requested_at,
                )
                for policy in selected
            )
            report, diagnostics = self.engine.evaluate(
                auth.session_id,
                subject,
                self.reader.evaluation,
                at,
                packages,
                work_language=work_language,
            )
            facts = {
                **facts,
                "change_facts": diagnostics.get("change_facts", []),
                "summary": [
                    *facts["summary"],
                    *[row["summary"] for row in diagnostics.get("change_facts", [])],
                ],
            }
            history = diagnostics["historical_responsibilities"]
            record_status = []
            if purpose_of(purpose) == "result":
                for policy in selected:
                    if not policy.launch_only:
                        continue
                    available = any(
                        h["criterion"] == policy.id
                        and h["kind"] in {"actual_action", "completion_claim"}
                        and h["finding"] != "unknown"
                        for h in history
                    )
                    record_status.append(
                        {
                            "criterion": policy.id,
                            "status": "provided" if available else "pending",
                            "reason": message(
                                work_language,
                                "已提供可核验的实际行动或明确完成声明，见历史层具体结果。",
                            )
                            if available
                            else message(
                                work_language,
                                "未提供可核验的实际行动或明确完成声明记录；该报告事项待核验，不代表没有发生。",
                            ),
                        }
                    )
            diagnostics["result_record_status"] = record_status
            report = attach_sections(
                report,
                self.reader,
                auth,
                subject,
                requested_at,
                facts,
                history,
                diagnostics["rule_items"],
                tuple(
                    item["criterion"] + "：" + item["reason"]
                    for item in record_status
                    if item["status"] == "pending"
                ),
                work_language=work_language,
            )
            result = {
                "subject": subject.model_dump(mode="json"),
                "evaluated_at": at.model_dump(mode="json"),
                "requested_at": requested_at.model_dump(mode="json"),
                "decision": chosen,
                "decision_origin": origin,
                "verified_facts": facts,
                "historical_responsibilities": history,
                "result_record_status": record_status,
                "source_issues": [
                    {"status": "pending", "reason": message(work_language, SAFE_REASON)}
                ]
                if any(p.rule_context.get("source_issues") for p in packages)
                else [],
                "feedback": report.model_dump(mode="json"),
                "diagnostics": diagnostics,
            }
            if reference_gap:
                result["pending_reason"] = "declared_reference_unverified"
            results.append(result)
        return {
            "reviews": results,
            "current_state_assessment": None,
            "boundary": "Each exact work uses its formation point; local source gaps do not erase other verified output.",
        }

    def handle(self, auth, request, requested_at, *, decision=UNSET):
        """Pure handler consuming the fixed c9 decision/followup fields.

        The explicit keyword remains available to the trusted adapter. An
        omitted ReviewInput field falls back to vetted structure,
        and an explicit None preserves uncertainty without forcing a form.
        """
        work_language = self.work_language
        if decision is UNSET:
            fields = getattr(type(request), "model_fields", None)
            if fields is not None:
                if "decision" in fields and "decision" in request.model_fields_set:
                    decision = request.decision
            elif hasattr(request, "decision"):
                decision = request.decision
        if isinstance(request, C.ReviewRequest):
            if (
                request.session_id != auth.session_id
                or request.as_of != requested_at
                or request.evaluation != self.reader.evaluation
            ):
                raise ProtocolError("review_binding_mismatch")
            # Saved None is an intentional recorded value, never re-inferred.
            if decision is UNSET:
                decision = request.decision
        result = self.review(
            auth,
            request.subjects,
            purpose=request.purpose,
            scope=request.scope,
            question=request.question,
            requested_at=requested_at,
            decision=decision,
        )
        result["followup_of"] = [
            r.model_dump(mode="json") for r in getattr(request, "followup_of", ())
        ]
        result["followup_status"] = "linked_not_resolved" if result["followup_of"] else None
        result["followup_evidence_status"] = "not_evaluated" if result["followup_of"] else None
        if result["followup_of"]:
            note = message(
                work_language,
                "关联异议或补证已记录；其中引文默认未核实，需按实际源版本、原文、时点与支持关系重新核验，关联本身不代表采信或解决。",
            )
            for entry in result["reviews"]:
                if entry["feedback"] is not None:
                    raw = entry["feedback"]
                    raw["next_options"] = list(dict.fromkeys([*raw["next_options"], note]))
                    entry["feedback"] = C.FeedbackV2.model_validate(raw).model_dump(mode="json")
        return result
