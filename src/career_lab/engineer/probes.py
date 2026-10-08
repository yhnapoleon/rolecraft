"""Private offline candidates from authorized PM work; never a research suite."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

from career_lab.contracts import v2 as C
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.storage.v2_lifecycle import point
from career_lab.storage.v2_store import TransactionView, V2Store

from .files import encode, file_ref, publish
from .identity import source_version


@dataclass(frozen=True)
class TextSelection:
    field: str = "content"
    spans: tuple[str, ...] = ()
    confirmed: bool = False


def free_candidates(
    product: C.WorkProductVersion,
    selection: TextSelection,
    executor: C.Executor,
) -> list[dict[str, Any]]:
    if not selection.confirmed or not selection.spans:
        raise C.ProtocolError("engineer_extraction_confirmation_required")
    text = product.content
    if selection.field == "body":
        if not isinstance(product.structured_payload, C.TextPayload):
            raise C.ProtocolError("engineer_extraction_field_invalid")
        text = product.structured_payload.body
    elif selection.field != "content":
        raise C.ProtocolError("engineer_extraction_field_invalid")
    result = []
    intervals = []
    for span in selection.spans:
        try:
            start, end = (int(part) for part in span.split(":"))
        except ValueError:
            raise C.ProtocolError("engineer_extraction_span_invalid") from None
        if not 0 <= start < end <= len(text) or any(start < b and a < end for a, b in intervals):
            raise C.ProtocolError("engineer_extraction_span_invalid")
        intervals.append((start, end))
        result.append(
            {
                "original_text": text[start:end],
                "source_location": {"field": selection.field, "start": start, "end": end},
                "source_case": None,
                "test_intent": {"intent": "", "declared_category": None, "declared_expected": None},
                "confirmation": {
                    "executor": executor,
                    "source_content_hash": product.content_hash,
                    "method": "explicit_cli_confirmation",
                },
            }
        )
    return result


def plan_candidates(product: C.WorkProductVersion) -> list[dict[str, Any]]:
    payload = product.structured_payload
    if not isinstance(payload, C.TestPlanPayload) or not payload.cases:
        raise C.ProtocolError("engineer_test_plan_required")
    return [
        {
            "original_text": case.query,
            "source_location": {"field": "structured_payload.cases", "case_id": case.id},
            "source_case": case.model_dump(mode="json"),
            "test_intent": {
                "intent": case.intent,
                "declared_category": case.declared_category,
                "declared_expected": case.declared_expected,
            },
        }
        for case in payload.cases
    ]


def candidate_files(
    view: TransactionView,
    module: ScenarioModule,
    auth: C.AuthContext,
    product_ref: C.ObjectRef,
    selection: TextSelection,
) -> dict[str, bytes]:
    module.check_bindings(view.bindings)
    if not view.reference_allowed(product_ref):
        raise C.ProtocolError("engineer_product_unavailable", status=404)
    product = C.WorkProductVersion.model_validate(view.get(product_ref).content)
    raw = encode(product)
    source = {
        "product_ref": product_ref,
        "product_file": file_ref("source-product.json", raw),
        "content_hash": product.content_hash,
        "bindings": view.bindings,
        "as_of": point(view.state),
        "structure_id": module.package.bundle.structure_id,
        "split": module.package.bundle.split,
        "work_language": module.work_language,
    }
    if isinstance(product.structured_payload, C.TestPlanPayload):
        if selection.spans or selection.confirmed or selection.field != "content":
            raise C.ProtocolError("engineer_extraction_selection_conflict")
        candidates = plan_candidates(product)
    else:
        candidates = free_candidates(product, selection, auth.executor)
    if len(candidates) > 100 or any(
        not row["original_text"].strip() or len(row["original_text"]) > 4000 for row in candidates
    ):
        raise C.ProtocolError("engineer_probe_query_invalid")
    for candidate in candidates:
        candidate.update(
            status="pending_review",
            truth_status="unverified",
            allowed_usage="review_only",
            training_eligible=False,
            optimization_eligible=False,
        )
        candidate["id"] = "probe-candidate-" + C.digest(
            to_jsonable_python({"source": source, "candidate": candidate})
        )
    body = {
        "schema_version": 1,
        "kind": "engineer_probe_candidates",
        "source": source,
        "executor": auth.executor,
        "tool_versions": {"career-lab-engineer": source_version()},
        "suite_published": False,
        "probe_execution_performed": False,
        "candidates": candidates,
    }
    # Canonical encoding converts the existing frozen models without extending them.
    body = to_jsonable_python(body)
    body["id"] = "probe-candidates-" + C.digest(body)
    return {"source-product.json": raw, "candidates.json": encode(body)}


def export_candidates(
    store: V2Store,
    module: ScenarioModule,
    auth: C.AuthContext,
    product_id: str,
    product_version: int,
    output: Path,
    selection: TextSelection | None = None,
) -> dict[str, Any]:
    if auth.actor_id != "learner":
        raise C.ProtocolError("engineer_learner_required", status=403)
    ref = C.ObjectRef(
        session_id=auth.session_id, kind="product", object_id=product_id, version=product_version
    )

    def read(view: TransactionView) -> dict[str, bytes]:
        return candidate_files(view, module, auth, ref, selection or TextSelection())

    files = store.query(auth, read, operation="work_products.versions.list")
    publish(output, files)
    body = json.loads(files["candidates.json"])
    return {
        "candidate_batch_id": body["id"],
        "status": "pending_review",
        "candidates": len(body["candidates"]),
    }
