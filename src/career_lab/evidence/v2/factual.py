"""Verified reference and activity facts. No conclusion-quality or ability score."""

from career_lab.contracts.v2.core import ProtocolError, VersionPoint, canonical
from .ports import ActivityLedger
from .history import before
from .localization import message, validate_language
from .availability import unavailable, ACTIVITY_CODES

KINDS = ("material_read", "test_run", "question_sent", "reply_received", "learner_displayed")
NAMES = {
    "material_read": "材料读取",
    "test_run": "测试运行",
    "question_sent": "向同事提问",
    "reply_received": "实际收到回复",
    "learner_displayed": "向学员展示",
}


def reference_key(ref):
    return (ref.session_id, ref.kind, ref.object_id, ref.version, ref.config_version)


def factual_feedback(
    reader, auth, subject, at, requested_at, *, work_language="zh", anchor_mode="product_version"
):
    from .assembler import EvidenceAssemblerV2

    record = reader.read(auth, subject, at)
    resolver = EvidenceAssemblerV2(reader)
    if anchor_mode not in {"product_version", "submission"}:
        raise ProtocolError("invalid_evaluation_anchor")
    if anchor_mode == "product_version" and record.created_at != at:
        raise ProtocolError("subject_point_mismatch", status=409)
    if anchor_mode == "submission" and not before(record.created_at, at):
        raise ProtocolError("subject_point_mismatch", status=409)
    refs = []
    seen = set()
    source_keys = set()
    exact_sources = set()
    effective_sources = set()
    expired_sources = set()
    for ref in record.declared_refs:
        key = canonical(ref)
        if key in seen:
            continue
        seen.add(key)
        source_keys.add(reference_key(ref))
        row = {
            "ref": ref.model_dump(mode="json"),
            "status": "unavailable",
            "valid_at_subject": None,
            "semantic_support": "not_established",
        }
        try:
            resolved = resolver.resolve(auth, ref, at)
            row.update(
                status="exact_reference_verified",
                valid_at_subject=resolved.ref.valid_until_seq is None
                or at.business_seq < resolved.ref.valid_until_seq,
            )
            exact_sources.add(reference_key(ref))
            (effective_sources if row["valid_at_subject"] else expired_sources).add(
                reference_key(ref)
            )
        except KeyError:
            pass
        except ProtocolError as error:
            if error.code in {
                "future_evidence",
                "evidence_version_mismatch",
                "evidence_quote_mismatch",
                "evidence_time_mismatch",
                "source_time_unknown",
            }:
                row["status"] = error.code
            elif unavailable(error):
                row["status"] = "unavailable"
            else:
                raise
        refs.append(row)
    ledger = reader.activity_log(auth, at) if hasattr(reader, "activity_log") else ActivityLedger()
    zero = VersionPoint(business_seq=0, workspace_revision=0, storage_revision=0)
    complete = dict(ledger.completeness)
    full_window = (
        ledger.covered_from is not None
        and before(ledger.covered_from, zero)
        and ledger.covered_through is not None
        and before(at, ledger.covered_through)
        and ledger.captured_at is not None
        and before(at, ledger.captured_at)
        and auth.allowed_objects is None
    )
    rows = []
    broken = set()
    seen_events = set()
    for event in ledger.records:
        if event.kind not in KINDS:
            raise ProtocolError("invalid_activity_kind")
        if not before(event.occurred_at, at):
            continue
        key = reference_key(event.ref)
        if key in seen_events:
            continue
        seen_events.add(key)
        try:
            checked = resolver.resolve(auth, event.ref, at)
            source = reader.read(auth, event.ref, at)
            if (
                source.created_at != event.occurred_at
                or source.executor is None
                or source.executor != event.executor
                or source.activity_kind != event.kind
                or source.activity_target != event.target
                or source.actor_id != event.actor_id
            ):
                raise ProtocolError("activity_provenance_mismatch")
            if event.ref.session_id != auth.session_id:
                raise ProtocolError("activity_provenance_mismatch")
            if event.kind in {"reply_received", "learner_displayed"}:
                if event.target is None:
                    raise ProtocolError("activity_target_missing")
                resolver.resolve(auth, event.target, event.occurred_at)
                target = reader.read(auth, event.target, event.occurred_at)
                expected = "question_sent" if event.kind == "reply_received" else "reply_received"
                if target.activity_kind != expected:
                    raise ProtocolError("activity_target_mismatch")
            rows.append(
                {
                    "kind": event.kind,
                    "ref": checked.ref.model_dump(mode="json"),
                    "occurred_at": event.occurred_at.model_dump(mode="json"),
                    "executor": event.executor.model_dump(mode="json"),
                    "actor_id": event.actor_id,
                    "target": event.target.model_dump(mode="json") if event.target else None,
                    "counterparty": event.counterparty,
                }
            )
        except (KeyError, ProtocolError) as error:
            if not unavailable(error) and not (
                isinstance(error, ProtocolError) and error.code in ACTIVITY_CODES
            ):
                raise
            broken.add(event.kind)
    from career_lab.contracts.v2.core import EvidenceRefV2, ObjectRef

    present = {(r["kind"], reference_key(EvidenceRefV2.model_validate(r["ref"]))) for r in rows}
    for row in rows:
        if row["kind"] in {"reply_received", "learner_displayed"} and row["target"]:
            expected = "question_sent" if row["kind"] == "reply_received" else "reply_received"
            if (expected, reference_key(ObjectRef.model_validate(row["target"]))) not in present:
                broken.add(expected)
    totals = {}
    for kind in KINDS:
        actual = [r for r in rows if r["kind"] == kind]
        known = full_window and complete.get(kind) is True and kind not in broken
        totals[kind] = {
            "status": "complete" if known else "unknown",
            "count": len(actual) if known else None,
            "verified_records": len(actual),
        }
    from .work_summary import work_summary

    summary = work_summary(totals, len(exact_sources), rows, work_language)
    summary += [
        message(
            work_language,
            "作品明确关联{p0}个来源、{p1}处去重引用；原文/版本已核对{p2}个，其中在作品参照点有效{p3}个、已失效{p4}个。失效来源保留历史用途；引用真实不等于支持结论。",
            p0=len(source_keys),
            p1=len(refs),
            p2=len(exact_sources),
            p3=len(effective_sources),
            p4=len(expired_sources),
        )
    ]
    for kind in KINDS:
        value = totals[kind]
        if value["status"] == "complete":
            summary.append(
                message(
                    work_language,
                    "作品形成前完整授权日志中的{p0}记录：{p1}条。",
                    p0=message(work_language, NAMES[kind]),
                    p1=value["count"],
                )
            )
        else:
            summary.append(
                message(
                    work_language,
                    "{p0}日志完整性未知；已核实{p1}条，不能据此断言没有发生。",
                    p0=message(work_language, NAMES[kind]),
                    p1=value["verified_records"],
                )
            )
    if any(r["executor"]["kind"] == "external_agent" for r in rows):
        summary.append(message(work_language, "含外部Agent执行记录；不视为学员独立调查或理解。"))
    summary.append(
        message(work_language, "提问、收到回复、向学员展示和理解分别记录；当前无法判断独立理解。")
    )
    if anchor_mode == "submission":
        summary = [
            text.replace("作品形成前完整授权日志", "提交时点前完整授权日志").replace(
                "before the work was created", "before the submission"
            )
            for text in summary
        ]
    return {
        "section": "verified_facts",
        "subject": subject.model_dump(mode="json"),
        "as_of": at.model_dump(mode="json"),
        "requested_at": requested_at.model_dump(mode="json"),
        "reference_grain": "exact_ref_and_quote; source_count_by_object_version_config",
        "declared_source_count": len(source_keys),
        "declared_citation_count": len(refs),
        "verified_source_count": len(exact_sources),
        "exact_source_count": len(exact_sources),
        "effective_source_count": len(effective_sources),
        "expired_source_count": len(expired_sources),
        "verified_source_count_basis": "exact_text_and_version_only",
        "references": refs,
        "activity_records": rows,
        "activity_totals": totals,
        "summary": summary,
        "activity_window": {
            "covered_from": ledger.covered_from.model_dump(mode="json"),
            "covered_through": ledger.covered_through.model_dump(mode="json"),
            "captured_at": ledger.captured_at.model_dump(mode="json"),
        }
        if ledger.covered_from is not None
        and ledger.covered_through is not None
        and ledger.captured_at is not None
        else None,
        "authorship": {
            k: getattr(record, k).model_dump(mode="json") if getattr(record, k) else None
            for k in ["author", "executor", "adopter"]
        },
        "independent_understanding": "unobserved",
        "conclusion_quality": "not_scored",
    }
