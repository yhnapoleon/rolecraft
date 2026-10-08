"""Synthetic, validated protocol examples. These are not business or experiment results."""

from datetime import datetime, timezone
from typing import get_origin, get_args, Annotated, Literal, Union
import types
from pydantic import BaseModel
from . import core

STAMP = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
LABELS = {
    "relation": ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT"),
    "criterion": ("MET", "PARTIAL", "NOT_MET", "INSUFFICIENT", "NOT_APPLICABLE"),
    "trajectory_diagnosis": ("diagnosed", "no_issue", "insufficient"),
    "acquisition": ("effective", "ineffective", "undetermined"),
}


def sample_value(typ, name=""):
    origin = get_origin(typ)
    args = get_args(typ)
    if origin is Annotated:
        return sample_value(args[0], name)
    if origin is Literal:
        return args[0]
    if origin in (Union, types.UnionType):
        return sample_value(next(x for x in args if x is not type(None)), name)
    if origin in (tuple, list):
        return () if origin is tuple else []
    if origin is dict:
        return {}
    if isinstance(typ, type) and issubclass(typ, BaseModel):
        return sample_model(typ, name)
    if typ is datetime:
        return STAMP
    if typ is bool:
        return False
    if typ is int:
        return 1
    if typ is float:
        return 1.0
    if typ is str:
        if name == "base_commit":
            return "80cf1f6189cd25610d609f44283ff9668582d759"
        if name.endswith(("hash", "digest")) or name == "sha256":
            return "0" * 64
        return "example"
    return "example"


def sample_model(model, context=""):
    from . import (
        ObjectRef,
        RevisionCycle,
        AssistantConfig,
        StoredObject,
        WorldStateV2,
        VersionPoint,
        WorkspaceTask,
    )

    data = {}
    for name, f in model.model_fields.items():
        if not f.is_required():
            continue
        data[name] = sample_value(f.annotation, name)
        for constraint in f.metadata:
            minimum = getattr(constraint, "min_length", None)
            if minimum and isinstance(data[name], (tuple, list)) and not data[name]:
                item_type = get_args(f.annotation)[0]
                data[name] = tuple(sample_value(item_type, name) for _ in range(minimum))
    n = model.__name__
    if n == "FileRef":
        data.update(path="files/payload.json", sha256=core.digest({}))
    if n in {"VersionPoint", "WorldStateV2"}:
        data.update(business_seq=0, workspace_revision=0, storage_revision=0)
    if n in {"ObjectRef", "EvidenceRefV2"}:
        kind = {
            "cycle": "cycle",
            "parent_submission": "submission",
            "product": "product",
            "reply_ref": "turn",
            "request": "business_request",
        }.get(context, "document")
        data.update(kind=kind, object_id="example", version=1)
        if n == "EvidenceRefV2":
            data["observed_at_seq"] = 0
    if n == "BeliefFact":
        data["status"] = "unknown"
    if n == "ImportReference":
        data["status"] = "unverified_local"
    if n == "BranchManifest":
        data["boundary"] = data["boundary"].model_copy(
            update={"start_seq": 0, "end_seq": 0, "storage_revision": 0}
        )
    if n == "CriterionInput":
        raw = data["evidence"].model_dump(mode="json")
        raw.update(task_type="criterion", criterion="example")
        raw["input_hash"] = core.digest({k: v for k, v in raw.items() if k != "input_hash"})
        data["evidence"] = type(data["evidence"]).model_validate(raw)
    if n == "BusinessBasis":
        from .world import assistant_config_content_hash

        data["content_hash"] = assistant_config_content_hash(data["config"])
    if n == "AnnotationDecision":
        data["label"] = "SUPPORTED"
    if n == "ModelPrediction":
        data.update(labels=LABELS[data["task_type"]], probabilities=(1 / 3, 1 / 3, 1 / 3))
    if n == "ModelBundle":
        data["labels"] = LABELS[data["task_type"]]
    if n == "DecisionResult":
        data["answers"] = {}
    if n == "TestResultV2":
        config = data["config"].requested
        data["config_ref"] = ObjectRef(
            session_id=config.session_id,
            kind="config",
            object_id=config.id,
            version=config.version,
            config_version=config.config_version,
        )
    if n == "ScenarioBundle":
        from . import FileRef

        f = sample_model(FileRef)
        data.update(files=(f,), public_files=(f.path,), private_files=())
    if n == "SplitManifest":
        data["independent_structure_count"] = 0
    if n == "DatasetRecordV2":
        data["label_ref"] = data["label_ref"].model_copy(update={"path": "labels/example.json"})
        data["input_hash"] = core.digest(data["model_input"])
    if n == "LegacyProvenance":
        data["original_hash"] = core.digest(data["raw"])
    if n == "LegacyAnnotation":
        data["original_hash"] = core.digest(data["original"])
    if n == "WorkProductVersion":
        data["content_hash"] = core.digest({"content": "", "structured_payload": None})
    if n == "ToolSchema":
        data["parameters_hash"] = core.digest(data["parameters"])
    if n == "StepResult":
        data.update(status="failed", error_code="synthetic_unavailable")
    if n == "ProviderRequest":
        data["tools_digest"] = core.digest([])
    if n == "DecisionRequest":
        data["input_hash"] = core.digest(data["observation"])
    if n == "WorkspaceImport":
        data["package_hash"] = core.digest([x.model_dump(mode="json") for x in data["items"]])
    if n == "JobRequest":
        data["name"] = "v2.example"
    if n in {"ObjectWrite", "StoredObject"}:
        task = sample_model(WorkspaceTask)
        data["ref"] = ObjectRef(
            session_id=task.session_id, kind="task", object_id=task.id, version=task.revision
        )
        data["content"] = task.model_dump(mode="json")
        if n == "ObjectWrite":
            data["expected_head"] = 0
        else:
            data["created_storage_revision"] = 0
    if n == "SnapshotExport":
        state = sample_model(WorldStateV2)
        state = state.model_copy(update={"cycle_id": "cycle"})
        cycle = RevisionCycle(
            id="cycle",
            session_id=state.session_id,
            opened_at=VersionPoint(business_seq=0, workspace_revision=0, storage_revision=0),
            base_state_ref=core.digest(state),
        )
        config = AssistantConfig(id="config", session_id=state.session_id, domains=("faq",))
        data.update(
            state=state,
            session_id=state.session_id,
            objects=(
                StoredObject(
                    ref=ObjectRef(
                        session_id=state.session_id, kind="cycle", object_id="cycle", version=1
                    ),
                    content=cycle.model_dump(mode="json"),
                    visible_to=("learner",),
                    created_storage_revision=0,
                ),
                StoredObject(
                    ref=ObjectRef(
                        session_id=state.session_id,
                        kind="config",
                        object_id="config",
                        version=1,
                        config_version=0,
                    ),
                    content=config.model_dump(mode="json"),
                    visible_to=("learner",),
                    created_storage_revision=0,
                ),
            ),
        )
    if n in {"EvidencePackageV2", "SkillSpec", "SnapshotExport"}:
        key = {
            "EvidencePackageV2": "input_hash",
            "SkillSpec": "content_hash",
            "SnapshotExport": "snapshot_hash",
        }[n]
        full = model.model_construct(**data).model_dump(mode="json", exclude={key})
        data[key] = core.digest(full)
    return model.model_validate(data)
