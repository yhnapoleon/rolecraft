"""Separate business bytes, content review, evaluation semantics and execution identity."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from career_lab.contracts.v2 import (
    EvaluationBundle,
    ProtocolError,
    RuntimeBundle,
    digest,
    read_file,
)

if TYPE_CHECKING:
    from .loader import ScenarioPackage

ROOT = Path(__file__).resolve().parents[4]
PROTOCOL = "scenario-release-v1"
EVALUATION_VERSION = "feedback-rubric-v2-c2.1"
PROMPT_VERSION = "grounded-feedback-bilingual-v1"
RELEASE_PATH = "runtime/release.json"
# These are generated descriptions. Every other manifested file is business content.
GENERATED = frozenset(
    {
        "manifest.json",
        "runtime/bundle.json",
        "runtime/source-files.json",
        "runtime/evaluation.json",
        "runtime/evaluation-protocol.json",
        RELEASE_PATH,
    }
)


class ReviewLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["recorded", "not_recorded"]
    content_identity: str
    original_review_sha256: str | None = None
    reviewed_source_hash: str | None = None
    continuity_sha256: str | None = None


class ReleaseDescription(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: str
    revision: str
    content_identity: str
    content_files: dict[str, str]
    content_metadata: dict[str, JsonValue]
    original_manifest: str
    original_release_identity: str
    review: ReviewLink
    evaluation_version: str
    evaluation_signature: str
    prompt_version: str
    code_acceptance: str = "candidate_pending_regression"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def content_files(package: "ScenarioPackage") -> dict[str, str]:
    return {
        ref.path: sha(read_file(package.root, ref))
        for ref in package.bundle.files
        if ref.path not in GENERATED
    }


def business_metadata(manifest: dict[str, JsonValue]) -> dict[str, JsonValue]:
    metadata = {key: value for key, value in manifest.items() if key != "files"}
    for name in ("public_files", "private_files"):
        metadata[name] = [path for path in metadata[name] if path not in GENERATED]
    return metadata


def evaluation_signature(root: Path, bundle: EvaluationBundle) -> str:
    protocol = json.loads(read_file(root, bundle.protocol))
    return digest(
        {
            "rubric": sha(read_file(root, bundle.rubric)),
            "rules": sha(read_file(root, bundle.rules)),
            "policies": protocol.get("policies"),
            "mode": bundle.mode,
            "model_retries": protocol.get("model_retries"),
            "semantic_status": protocol.get("semantic_status"),
        }
    )


def require_evaluation(
    root: Path, bundle: EvaluationBundle, version: str = EVALUATION_VERSION, *, language: str
) -> str:
    registry = json.loads((ROOT / "configs/evaluation/versions.json").read_text())
    entry = registry["versions"].get(version)
    signature = evaluation_signature(root, bundle)
    if (
        version != EVALUATION_VERSION
        or entry is None
        or signature not in entry["protocol_signatures"].get(language, [])
    ):
        raise ProtocolError("evaluation_version_unsupported", status=409)
    return signature


def require_behavior(version: str, output_digest: str, expected: dict[str, str]) -> None:
    """A changed behavior needs a new version and its own reviewed comparison evidence."""
    if expected.get(version) != output_digest:
        raise ProtocolError("evaluation_version_change_required", status=409)


def original_review(package: "ScenarioPackage", identity: str) -> ReviewLink:
    directory = ROOT / "scenarios/pm_pilot/v2/variants/reviews"
    continuity_raw = (directory / "content-continuity-2.9.6.json").read_bytes()
    continuity = json.loads(continuity_raw)
    raw = (directory / "content-approval-2.9.0.json").read_bytes()
    approval = json.loads(raw)
    if sha(raw) != continuity["independent_review"]["sha256"]:
        raise ProtocolError("content_review_changed", status=409)
    rows = [
        row
        for row in continuity["bindings"]
        if row["installed_scenario_hash"] == package.content_hash
        and row["scenario_id"] == package.bundle.id
        and row["work_language"] == package.locale
    ]
    if not rows:
        # The existing approval contains the four variants, not the main scenario.
        return ReviewLink(status="not_recorded", content_identity=identity)
    row = rows[0]
    approved = {
        (item["scenario_id"], item["work_language"], item["scenario_hash"])
        for item in approval["bundles"]
    }
    if approval["scope"] != "authored_content_only" or approval["verdict"] != "accepted":
        raise ProtocolError("content_review_unavailable", status=409)
    if (package.bundle.id, package.locale, row["reviewed_source_hash"]) not in approved:
        raise ProtocolError("content_review_unavailable", status=409)
    return ReviewLink(
        status="recorded",
        content_identity=identity,
        original_review_sha256=sha(raw),
        reviewed_source_hash=row["reviewed_source_hash"],
        continuity_sha256=sha(continuity_raw),
    )


def describe(package: "ScenarioPackage", revision: str) -> ReleaseDescription:
    previous = read_release(package)
    if previous is not None:
        return previous.model_copy(update={"revision": revision})
    files = content_files(package)
    metadata = business_metadata(package.bundle.model_dump(mode="json"))
    identity = digest({"files": files, "metadata": metadata})
    evaluation = EvaluationBundle.model_validate_json(
        (package.root / "runtime/evaluation.json").read_bytes()
    )
    return ReleaseDescription(
        protocol=PROTOCOL,
        revision=revision,
        content_identity=identity,
        content_files=files,
        content_metadata=metadata,
        original_manifest=(package.root / "manifest.json").read_text(),
        original_release_identity=package.content_hash,
        review=original_review(package, identity),
        evaluation_version=EVALUATION_VERSION,
        evaluation_signature=require_evaluation(package.root, evaluation, language=package.locale),
        prompt_version=PROMPT_VERSION,
    )


def read_release(package: "ScenarioPackage") -> ReleaseDescription | None:
    files = {ref.path: ref for ref in package.bundle.files}
    if RELEASE_PATH not in files:
        return None
    release = ReleaseDescription.model_validate_json(read_file(package.root, files[RELEASE_PATH]))
    if release.protocol != PROTOCOL:
        raise ProtocolError("release_protocol_unsupported", status=409)
    actual = content_files(package)
    original = json.loads(release.original_manifest)
    metadata = business_metadata(package.bundle.model_dump(mode="json"))
    old_files = {
        ref["path"]: ref["sha256"] for ref in original["files"] if ref["path"] not in GENERATED
    }
    if (
        actual != release.content_files
        or actual != old_files
        or metadata != release.content_metadata
        or metadata != business_metadata(original)
        or digest({"files": actual, "metadata": metadata}) != release.content_identity
        or release.review.content_identity != release.content_identity
        or sha(release.original_manifest.encode()) != release.original_release_identity
    ):
        raise ProtocolError("release_content_mismatch", status=409)
    expected_review = original_review(
        replace(package, content_hash=release.original_release_identity), release.content_identity
    )
    if release.review != expected_review or release.prompt_version != PROMPT_VERSION:
        raise ProtocolError("release_review_mismatch", status=409)
    evaluation = EvaluationBundle.model_validate_json(
        read_file(package.root, files["runtime/evaluation.json"])
    )
    if (
        require_evaluation(
            package.root, evaluation, release.evaluation_version, language=package.locale
        )
        != release.evaluation_signature
    ):
        raise ProtocolError("release_evaluation_mismatch", status=409)
    return release


def validate_runtime(
    package: "ScenarioPackage", runtime: RuntimeBundle
) -> ReleaseDescription | None:
    """Read both protocols; historical source digests remain evidence, not live-code locks."""
    source = json.loads(read_file(package.root, runtime.source.overlay))
    release = read_release(package)
    if release is not None:
        if (
            source.get("protocol") != PROTOCOL
            or source.get("content_identity") != release.content_identity
        ):
            raise ProtocolError("runtime_protocol_mismatch", status=409)
        return release
    # Legacy descriptions must remain internally intact and name the supported old contract.
    if digest(source["owned_code"]) != runtime.source.source_digest:
        raise ProtocolError("runtime_source_mismatch", status=409)
    foundation = ROOT / "docs/contracts/expansion-v3/manifest.json"
    if sha(foundation.read_bytes()) != source["foundation_contract_sha256"]:
        raise ProtocolError("runtime_contract_mismatch", status=409)
    return None


def protocol_overlay(release: ReleaseDescription) -> dict[str, JsonValue]:
    return {
        "protocol": PROTOCOL,
        "content_identity": release.content_identity,
        "evaluation_version": release.evaluation_version,
    }
