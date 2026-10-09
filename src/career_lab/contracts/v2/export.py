"""Export a candidate freeze; the manifest's exact SHA256 is its revision."""

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from pydantic import JsonValue

from career_lab.contracts.v2.compatibility import without_provenance
from career_lab.contracts.v2.discovery import REQUEST_MODELS, public_models
from career_lab.contracts.v2.examples import sample_model
from career_lab.contracts.v2.manifest_history import (
    ERROR_CODES,
    ERROR_HTTP_POLICY,
    MANIFEST_HISTORY,
)

CONSUMERS = {
    "W02": [
        "ScenarioBundle",
        "RoleSpecV2",
        "FactV2",
        "MaterialV2",
        "SourceFragment",
        "AssistantConfig",
        "EffectiveConfig",
        "TestRequestV2",
        "TestResultV2",
        "BusinessRequest",
        "BusinessDecision",
        "ActionInput",
        "ObjectWrite",
        "EventDraft",
        "Command",
    ],
    "W03": [
        "WorkspaceTask",
        "WorkProductVersion",
        "ProductShare",
        "WorkspaceImport",
        "ImportResult",
        "LegacyProductImport",
        "TaskCreate",
        "TaskPatch",
        "ProductCreate",
        "ProductEdit",
        "ShareCreate",
        "ShareUpdate",
        "ObjectWrite",
        "Command",
    ],
    "W04": [
        "RoleContext",
        "DisclosureRecord",
        "SourceFragment",
        "JobContextSnapshot",
        "TurnInput",
        "ApprovalInput",
        "BusinessRequest",
        "BusinessDecision",
        "ProductShare",
    ],
    "W05": [
        "EvidencePackageV2",
        "FeedbackV2",
        "ReviewRequest",
        "RevisionCycle",
        "SubmissionV2",
        "ReviewInput",
        "SubmitInput",
        "BeginRevisionInput",
        "EvaluationBundle",
        "RuleBound",
        "TerminalEvaluation",
        "JobRequest",
        "JobEnvelope",
    ],
    "W06": [
        "AuthContext",
        "Executor",
        "DelegationInput",
        "DelegationGrant",
        "DelegationRevoke",
        "Observation",
        "ToolSchema",
        "Command",
        "JobEnvelope",
        "ResourcePage",
    ],
    "W07": [
        "DatasetRecordV2",
        "AnnotationV2",
        "AnnotationPass",
        "LegacyAnnotation",
        "SplitManifest",
        "Lineage",
        "Provenance",
        "RelationInput",
        "CriterionInput",
        "TrajectoryInput",
        "DecisionPointInput",
        "SnapshotExport",
    ],
    "W08": [
        "ModelBundle",
        "ModelPrediction",
        "RuntimeBundle",
        "EvaluationBundle",
        "CandidateBundle",
        "FileRef",
        "SourceIdentity",
        "TestCampaign",
    ],
    "W09": [
        "ActionProposal",
        "Observation",
        "BeliefState",
        "RunManifest",
        "Budget",
        "ModelAttemptUsage",
        "Trajectory",
        "SnapshotExport",
        "RestoreResult",
        "JobContextSnapshot",
    ],
    "W10": [
        "ActionBoundary",
        "BranchManifest",
        "SnapshotExport",
        "RestoreResult",
        "Trajectory",
        "Diagnosis",
        "TerminalEvaluation",
    ],
    "W11": ["ScenarioBundle", "SplitManifest", "Lineage", "TestCampaign", "FileRef"],
    "W12": [
        "DecisionRequest",
        "DecisionResult",
        "SkillSpec",
        "SkillBundle",
        "CandidateBundle",
        "RuntimeBundle",
        "EvaluationBundle",
        "TestCampaign",
    ],
    "W13": [
        "EngineerPack",
        "EngineerSubmission",
        "RegressionReport",
        "AssistantConfig",
        "ObjectRef",
    ],
    "W14": ["Command", "AuthContext", "TransactionResult", "ErrorResponse", "V2Response"],
    "W15": ["AnnotationV2", "FeedbackV2", "EvaluationBundle", "Provenance"],
}

CONSUMERS["W02"] += [
    "BusinessBasis",
    "ScenarioStateV2",
    "MaterialMetadata",
    "TestExecutionMetadata",
    "RetrievedChunk",
    "ExternalReference",
]
CONSUMERS["W03"] += [
    "ProductAdopt",
    "TaskBatch",
    "ImportConflict",
    "ImportVersionMap",
    "PublicTransactionResult",
]
CONSUMERS["W04"] += [
    "ObservedFragment",
    "ProviderRequest",
    "ProviderResult",
    "ProviderCapabilities",
    "ActualConsumption",
]
CONSUMERS["W06"] += ["DelegationJobCapacity", "OperationAvailability"]
CONSUMERS["W06"] += [
    "StepResult",
    "ObservedFragment",
    "PublicState",
    "PublicEvent",
    "PublicTransactionResult",
    "ActualConsumption",
]
CONSUMERS["W07"] += ["ExternalReference", "ObservedFragment", "ActualConsumption"]
CONSUMERS["W08"] += ["ProviderRequest", "ProviderReply", "ProviderResult", "ProviderCapabilities"]
CONSUMERS["W09"] += [
    "StepResult",
    "ProviderRequest",
    "ProviderResult",
    "ProviderCapabilities",
    "ActualConsumption",
    "PublicTransactionResult",
]
CONSUMERS["W10"] += ["ExternalReference", "ObservedFragment"]
CONSUMERS["W12"] += [
    "ProviderRequest",
    "ProviderResult",
    "ProviderCapabilities",
    "ActualConsumption",
]
CONSUMERS["W13"] += ["TestExecutionMetadata", "RetrievedChunk", "BusinessBasis"]
CONSUMERS["W14"] += ["PublicState", "PublicEvent", "PublicTransactionResult"]

CONSUMERS["W04"] += ["PublicDisclosureSource", "PublicDisclosureRecord"]
CONSUMERS["W06"] += [
    "PublicDisclosureSource",
    "PublicDisclosureRecord",
    "RequestResultQuery",
    "RequestJobResult",
    "RequestResult",
]
CONSUMERS["W09"] += ["RequestResultQuery", "RequestJobResult", "RequestResult", "ProviderReceipt"]
CONSUMERS["W07"] += ["ProviderReceipt", "DatasetMetadataV2", "DatasetSnapshotMetadata"]
CONSUMERS["W08"] += ["ProviderReceipt", "DatasetMetadataV2", "DatasetSnapshotMetadata"]
CONSUMERS["W12"] += ["ProviderReceipt"]
CONSUMERS["W03"] += [
    "ImportedTaskSource",
    "WorkspaceImportReceipt",
    "WorkspaceProductRead",
    "WorkspaceProductPage",
    "WorkspaceSharePage",
]
CONSUMERS["W05"] += ["FeedbackReadBoundary"]
CONSUMERS["W05"] += [
    "FeedbackReferenceCheck",
    "FeedbackActivity",
    "FeedbackActivityCount",
    "FeedbackActivityWindow",
    "VerifiedFactsSnapshot",
    "HistoricalResponsibilityFinding",
    "HistoricalResponsibilitiesSnapshot",
    "FeedbackResponseRecord",
    "FeedbackResponseCreate",
]
CONSUMERS["W04"] += [
    "RoleAuditScope",
    "RoleAuditReceivedShare",
    "RoleAuditMemory",
    "RoleGenerationAudit",
]
for consumer in ("W04", "W05", "W06", "W09", "W14"):
    CONSUMERS[consumer] += ["JobRefreshRecord"]

for consumer in ("W06", "W14"):
    CONSUMERS[consumer] += [
        "ShownPractice",
        "PracticeChoiceInput",
        "DelegationSummary",
        "DelegationListPage",
        "DelegationListResult",
        "DelegationListResponse",
        "PracticeView",
        "PracticeReadResponse",
        "PracticePlan",
        "PracticeSession",
        "PracticeChoiceResult",
        "PracticeChoiceResponse",
    ]


def integration_example(model):
    from career_lab.contracts.v2 import (
        DisclosedFragment,
        EvidenceRefV2,
        Executor,
        FeedbackReferenceCheck,
        FeedbackResponseRecord,
        ImportedTaskSource,
        ImportResult,
        LegacyProvenance,
        ObjectRef,
        ProviderMessage,
        RoleAuditMemory,
        RoleAuditReceivedShare,
        RoleAuditScope,
        RoleGenerationAudit,
        VerifiedFactsSnapshot,
        VersionPoint,
        WorkProductVersion,
        WorkspaceImportReceipt,
        WorkspaceProductPage,
        WorkspaceProductRead,
        WorkspaceSharePage,
        digest,
    )
    from career_lab.contracts.v2.examples import STAMP

    scope = RoleAuditScope(
        capabilities=("read", "act"),
        actor_id="learner",
        executor=Executor(id="human:example", kind="human"),
        credential_id="example",
    )
    fragment = DisclosedFragment(
        ref=EvidenceRefV2(
            session_id="example", kind="product", object_id="product", version=1, observed_at_seq=0
        ),
        text="Synthetic private receipt.",
        channel="received_share",
        verification="verified",
    )
    if model is RoleAuditScope:
        return scope
    if model is RoleAuditReceivedShare:
        return model(
            share=ObjectRef(session_id="example", kind="share", object_id="share", version=1),
            product=ObjectRef(session_id="example", kind="product", object_id="product", version=1),
            role_id="tech_lead",
            received_at=sample_model(VersionPoint),
            fragment=fragment,
        )
    if model is RoleAuditMemory:
        return model(fragment=fragment, role_id="tech_lead")
    if model is RoleGenerationAudit:
        message = ProviderMessage(
            role="system", content="Synthetic private prompt; no model call occurred."
        )
        return model(
            job_id="example-job",
            job_attempt=1,
            request=ObjectRef(session_id="example", kind="role_turn", object_id="turn", version=1),
            scope=scope,
            prompt_messages=(message,),
            prompt_hash=digest([{"role": message.role, "content": message.content}]),
            history_revision=digest("synthetic history"),
        )
    from career_lab.contracts.v2 import FeedbackReadBoundary

    if model is FeedbackReadBoundary:
        return model(
            path="/business_response",
            content_hash=digest("Synthetic bounded text"),
            dependencies=(
                ObjectRef(session_id="example", kind="product", object_id="product", version=1),
            ),
        )
    from career_lab.contracts.v2 import DelegationJobCapacity, OperationAvailability

    if model is DelegationJobCapacity:
        return model(
            delegation_id="example",
            max_active_jobs=2,
            active_jobs=0,
            available_slots=2,
            observed_at=STAMP,
        )
    if model is OperationAvailability:
        return model(
            name="example", installed=False, ready=False, unavailable_code="module_unavailable"
        )
    if model is FeedbackReferenceCheck:
        return model(
            submitted_reference_hash=digest("synthetic missing reference"), status="unavailable"
        )
    if model is VerifiedFactsSnapshot:
        return model(
            subject=ObjectRef(session_id="example", kind="product", object_id="product", version=1),
            status="unknown",
            as_of=None,
            requested_at=sample_model(VersionPoint),
            captured_at=sample_model(VersionPoint),
            source_snapshot_hash=digest("synthetic unverified snapshot"),
            summary=("Formation point is unknown.",),
        )
    if model is FeedbackResponseRecord:
        return model(
            id="response",
            session_id="example",
            feedback=ObjectRef(
                session_id="example", kind="feedback", object_id="feedback", version=1
            ),
            kind="objection",
            text="Please reconsider this interpretation.",
            recorded_at=sample_model(VersionPoint),
            executor=Executor(id="human:example", kind="human"),
        )
    if model is WorkspaceProductRead:
        return model.model_validate(
            sample_model(WorkProductVersion).model_dump(mode="json") | {"visibility": None}
        )
    if model is ImportedTaskSource:
        source = sample_model(LegacyProvenance).model_copy(update={"original_kind": "task"})
        return model(
            task=ObjectRef(session_id="example", kind="task", object_id="task", version=1),
            source=source,
        )
    if model is WorkspaceImportReceipt:
        result = ImportResult(
            package_id="example",
            mode="apply",
            id_map={},
            unresolved=(),
            as_of=VersionPoint(business_seq=0, workspace_revision=1, storage_revision=1),
            applied=True,
        )
        return model(
            id="receipt",
            session_id="example",
            package_id="example",
            package_hash=digest([]),
            source_schema="browser-v1",
            source_session_id="legacy",
            fingerprint=digest("synthetic-example"),
            result=result,
            executor=Executor(id="human:example", kind="human"),
            created_at=STAMP,
        )
    if model is WorkspaceProductPage:
        return model(items=(), shares=(), sharing_complete=True, as_of=sample_model(VersionPoint))
    if model is WorkspaceSharePage:
        return model(items=(), sharing_complete=True, as_of=sample_model(VersionPoint))
    return sample_model(model)


def manifest_metadata() -> dict[str, JsonValue]:
    """Replay publication records without reading or modifying generated artifacts."""
    manifest: dict[str, JsonValue] = {}
    for record in MANIFEST_HISTORY:
        for field, value in record.items():
            previous = manifest.get(field)
            if isinstance(previous, dict) and isinstance(value, dict):
                previous.update(deepcopy(value))
            else:
                manifest[field] = deepcopy(value)
    return manifest


def dump(path: Path, data: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(root: Path, output: Path) -> dict[str, int | str]:
    """Export public wire contracts; root remains accepted for existing callers.

    Historical publication fingerprints come from the ordered metadata records,
    so an empty output directory and changes to source layout do not alter them.
    """
    from career_lab.api.app import create_app

    output.mkdir(parents=True, exist_ok=True)
    models = public_models()
    entries = {}
    for name, model in models.items():
        example = integration_example(model)
        dump(output / "schemas" / f"{name}.json", without_provenance(model.model_json_schema()))
        dump(output / "examples" / f"{name}.json", example.model_dump(mode="json"))
        entries[name] = {
            "owner": "W01",
            "schema_version": 2,
            "consumers": [wp for wp, names in CONSUMERS.items() if name in names]
            or ["shared-primitive"],
            "schema": f"schemas/{name}.json",
            "schema_sha256": sha(output / "schemas" / f"{name}.json"),
            "example": f"examples/{name}.json",
            "example_sha256": sha(output / "examples" / f"{name}.json"),
            "tests": [
                "tests/contracts/expansion_v3/test_freeze.py::test_all_frozen_models_examples_and_openapi_agree"
            ],
        }
    (output / "examples/files").mkdir(exist_ok=True)
    (output / "examples/files/payload.json").write_text("{}")
    (output / "examples/labels").mkdir(exist_ok=True)
    (output / "examples/labels/example.json").write_text("{}")
    app = create_app("sqlite:///:memory:")
    from career_lab.api.v4_extensions import mount_v4_extensions

    mount_v4_extensions(app)
    dump(output / "openapi.json", without_provenance(app.openapi()))
    app.state.store.close()
    dump(
        output / "errors.json",
        {"schema_version": 2, "codes": sorted(set(ERROR_CODES)), "http_policy": ERROR_HTTP_POLICY},
    )
    manifest = manifest_metadata()
    manifest.update(
        {
            "schemas": entries,
            "consumer_interfaces": CONSUMERS,
            "request_payloads": REQUEST_MODELS,
            "openapi": {"path": "openapi.json", "sha256": sha(output / "openapi.json")},
            "errors": {"path": "errors.json", "sha256": sha(output / "errors.json")},
        }
    )
    dump(output / "manifest.json", manifest)
    revision = "expansion-v3-" + sha(output / "manifest.json")
    (output / "revision.txt").write_text(revision + "\n")
    return {"models": len(models), "revision": revision, "manifest": str(output / "manifest.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.root.resolve(), args.output.resolve()), ensure_ascii=False))


if __name__ == "__main__":
    main()
