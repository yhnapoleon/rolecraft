import hashlib
import json
import math
from pathlib import Path

from career_lab.storage.sessions import digest


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def register_candidate(model_manifest, run_manifest, *, rubric_hash):
    model_manifest, run_manifest = Path(model_manifest).resolve(), Path(run_manifest).resolve()
    model = json.loads(model_manifest.read_text(encoding="utf-8"))
    run = json.loads(run_manifest.read_text(encoding="utf-8"))
    artifact = (model_manifest.parent / model["file"]).resolve()
    if not artifact.is_relative_to(model_manifest.parent) or file_hash(artifact) != model["sha256"]:
        raise ValueError("model hash mismatch")
    if model["revision"] != run["config"]["candidate"] or model["dataset_hash"] != run["dataset_hash"]:
        raise ValueError("model/report candidate or dataset mismatch")
    metrics_path = run_manifest.parent / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))["overall"]
    for key in ("accuracy", "macro_f1", "false_deduction", "joint_correctness"):
        if key not in metrics or not isinstance(metrics[key], (int,float)) or not math.isfinite(metrics[key]):
            raise ValueError("missing required evaluation metric")
    record = {"model_revision": model["revision"], "rubric_hash": rubric_hash, "dataset_hash": model["dataset_hash"],
              "evaluation_scope": run["config"]["split"], "metrics": metrics,
              "files": {str(p): file_hash(p) for p in (model_manifest, artifact, run_manifest, metrics_path)},
              "deployment_eligible": False, "purpose": "relation_eval_only"}
    return record | {"id": digest(record)}


def verify_record(record, rubric_hash):
    if record["rubric_hash"] != rubric_hash:
        raise ValueError("rubric changed; re-evaluation required")
    for path, expected in record["files"].items():
        if file_hash(path) != expected:
            raise ValueError("registered artifact/report hash changed")
    if record["id"] != digest({k: v for k, v in record.items() if k != "id"}):
        raise ValueError("registry record hash changed")


def select_deployment(candidates, candidate_id, reason):
    if not reason.strip():
        raise ValueError("selection requires reason")
    record = next(r for r in candidates if r["id"] == candidate_id)
    verify_record(record, record["rubric_hash"])
    if not record["deployment_eligible"] or record["purpose"] != "criterion_judge":
        raise ValueError("candidate is not verified for product deployment")
    return {"candidate_id": candidate_id, "reason": reason}
