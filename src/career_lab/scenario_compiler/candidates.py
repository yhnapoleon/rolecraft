"""Freeze current-protocol candidates without granting publication authority."""

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from career_lab.contracts.v2.core import FileRef, ProtocolError, Timestamp, read_file
from career_lab.contracts.v2.research import EvaluationBundle
from career_lab.reference_agent.journal import RunJournal
from career_lab.scenario_compiler.boundaries import validate_boundary
from career_lab.scenarios.v2.module import ScenarioModule


class EvaluationIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: Literal["scenario-candidate-v1"] = "scenario-candidate-v1"
    id: str
    author_label: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    created_at: Timestamp
    generator: Literal["manual"] = "manual"
    evaluation: EvaluationIdentity
    status: Literal["building", "candidate", "failed"] = "building"
    files: dict[str, str] = Field(default_factory=dict)
    error_code: str | None = None


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def require_evaluation(module: ScenarioModule, expected: EvaluationIdentity) -> None:
    ref = module.bindings.evaluation
    raw = read_file(module.package.root, ref)
    evaluation = EvaluationBundle.model_validate_json(raw)
    actual = EvaluationIdentity(id=evaluation.id, revision=evaluation.revision, sha256=sha(raw))
    if actual != expected:
        raise ProtocolError("candidate_evaluation_mismatch", status=409)


def freeze(
    source: Path, declaration: Path, output: Path, expected: EvaluationIdentity
) -> dict[str, str]:
    module = ScenarioModule(source)
    require_evaluation(module, expected)
    manifest = (source / "manifest.json").read_bytes()
    if sha(manifest) != module.package.content_hash:
        raise ProtocolError("candidate_source_changed", status=409)
    declared = declaration.read_bytes()
    json.loads(declared)
    members = (FileRef(path="manifest.json", sha256=sha(manifest)), *module.package.bundle.files)
    files = {}
    for ref in members:
        raw = read_file(source, ref)
        name = "package/" + ref.path
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        files[name] = sha(raw)
    (output / "declaration.json").write_bytes(declared)
    files["declaration.json"] = sha(declared)
    require_evaluation(ScenarioModule(output / "package"), expected)
    return files


def build_candidate(
    *,
    source: Path,
    declaration: Path,
    output: Path,
    author_id: str,
    revision: str,
    evaluation: EvaluationIdentity,
) -> dict[str, JsonValue]:
    if output.is_symlink():
        raise ProtocolError("candidate_destination_not_fresh", status=409)
    source, output = source.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(source):
        raise ProtocolError("candidate_destination_not_fresh", status=409)
    record = CandidateRecord(
        id=str(uuid4()),
        author_label=author_id,
        revision=revision,
        created_at=datetime.now(UTC),
        evaluation=evaluation,
    )
    output.mkdir(parents=True, mode=0o700)
    journal = RunJournal(output)
    with journal.locked():
        journal.save(record.model_dump(mode="json"))
        try:
            files = freeze(source, declaration, output, evaluation)
            record = record.model_copy(update={"status": "candidate", "files": files})
        except (OSError, ValueError) as error:
            code = error.code if isinstance(error, ProtocolError) else "candidate_input_invalid"
            record = record.model_copy(update={"status": "failed", "error_code": code})
        journal.save(record.model_dump(mode="json"))
    return validate_candidate(output)


def validate_candidate(output: Path) -> dict[str, JsonValue]:
    if not output.is_dir():
        raise ProtocolError("candidate_not_found", status=404)
    saved = RunJournal(output).load()
    if saved is None:
        raise ProtocolError("candidate_record_missing", status=409)
    record = CandidateRecord.model_validate(saved)
    base: dict[str, JsonValue] = {
        "candidate_id": record.id,
        "published": False,
        "generator": record.generator,
        "revision": record.revision,
        "package_status": "unverified",
    }
    if record.status != "candidate":
        return base | {
            "status": "failed" if record.status == "failed" else "unresolved",
            "error_code": record.error_code or "candidate_build_interrupted",
            "issues": [
                {
                    "code": record.error_code or "candidate_build_interrupted",
                    "location": {
                        "fact_source_value_mismatch": "facts.json",
                        "hidden_probe_in_public_material": "probes.json",
                        "candidate_evaluation_mismatch": "runtime/evaluation.json",
                    }.get(record.error_code, "package"),
                }
            ],
        }
    for name, identity in record.files.items():
        read_file(output, FileRef(path=name, sha256=identity))
    actual = {"declaration.json"} | {
        "package/" + str(path.relative_to(output / "package"))
        for path in (output / "package").rglob("*")
        if path.is_file()
    }
    if actual != set(record.files):
        raise ProtocolError("candidate_members_changed", status=409)
    module = ScenarioModule(output / "package")
    require_evaluation(module, record.evaluation)
    value = json.loads((output / "declaration.json").read_bytes())
    boundary = validate_boundary(value, installed_effects={}, confirmed_digest=None)
    return base | {
        "status": boundary.status,
        "package_status": "valid",
        "evaluation": record.evaluation.model_dump(mode="json"),
        "scenario_sha256": module.package.content_hash,
        "issues": [asdict(issue) for issue in boundary.issues],
    }


def publication_candidate(output: Path) -> dict[str, JsonValue]:
    report = validate_candidate(output)
    if report["package_status"] != "valid":
        return report
    return report | {
        "status": "needs_authorization",
        "error_code": "scenario_release_authority_unavailable",
    }


def attempt_summary(root: Path) -> dict[str, JsonValue]:
    """Count every directory in a dedicated attempt root, including unreadable work."""
    if not root.is_dir():
        raise ProtocolError("candidate_attempt_root_missing", status=404)
    attempts: list[dict[str, JsonValue]] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() and not path.is_symlink():
            continue
        entry: dict[str, JsonValue] = {
            "id": "unresolved-" + sha(path.name.encode()),
            "status": "unresolved",
            "generator": "unknown",
            "error_code": "candidate_record_unavailable",
        }
        if not path.is_symlink():
            try:
                record = CandidateRecord.model_validate(RunJournal(path).load())
                entry = {
                    "id": record.id,
                    "status": record.status if record.status != "building" else "unresolved",
                    "generator": record.generator,
                    "error_code": record.error_code,
                }
            except (OSError, ValueError):
                pass  # The attempt is counted even when its record cannot be interpreted.
        attempts.append(entry)
    return {
        "total_attempts": len(attempts),
        "by_status": dict(Counter(entry["status"] for entry in attempts)),
        "by_generator": dict(Counter(entry["generator"] for entry in attempts)),
        "attempts": attempts,
        "published": False,
    }
