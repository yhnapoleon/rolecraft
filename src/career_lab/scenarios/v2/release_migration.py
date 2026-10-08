"""Implementation of the formal CLI's content-preserving protocol migration."""

import json
import shutil
from pathlib import Path

from career_lab.contracts.v2 import (
    EvaluationBundle,
    FileRef,
    ProtocolError,
    RuntimeBundle,
    SourceIdentity,
    canonical,
)
from career_lab.contracts.v2.provenance import CodeIdentity
from career_lab.rubrics.v4.rubric_v2 import load_installed_policies, rules_document
from career_lab.runtime.provenance import execution_identity

from .loader import ScenarioPackage, load_package
from .release import (
    GENERATED,
    RELEASE_PATH,
    ROOT,
    ReleaseDescription,
    content_files,
    describe,
    protocol_overlay,
    require_evaluation,
    sha,
)


def _copy_members(package: ScenarioPackage, destination: Path) -> None:
    destination.mkdir(parents=True)
    for ref in package.bundle.files:
        target = destination / ref.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package.root / ref.path, target)


def _write_runtime(
    destination: Path,
    previous: RuntimeBundle,
    release: ReleaseDescription,
    revision: str,
    code: CodeIdentity,
) -> None:
    if code.commit is None or code.snapshot is None:
        raise ProtocolError("rebind_code_identity_unavailable", status=409)
    (destination / RELEASE_PATH).write_text(release.model_dump_json(indent=2) + "\n")
    path = "runtime/source-files.json"
    overlay = {**protocol_overlay(release), "exporter": code.model_dump(mode="json")}
    (destination / path).write_text(json.dumps(overlay, indent=2) + "\n")
    source = SourceIdentity(
        base_commit=code.commit,
        source_digest=code.snapshot,
        overlay=FileRef(path=path, sha256=sha((destination / path).read_bytes())),
        dependency_locks=previous.source.dependency_locks,
    )
    runtime = previous.model_copy(update={"revision": revision, "source": source})
    (destination / "runtime/bundle.json").write_text(runtime.model_dump_json(indent=2) + "\n")


def _write_evaluation(destination: Path, language: str) -> str:
    path = "runtime/evaluation.json"
    raw = (destination / path).read_bytes()
    load_installed_policies(
        destination, FileRef(path=path, sha256=sha(raw)), work_language=language
    )
    previous = EvaluationBundle.model_validate_json(raw)
    rules_path = "runtime/evaluation-rules.json"
    rules_raw = (canonical(rules_document()) + "\n").encode()
    (destination / rules_path).write_bytes(rules_raw)
    evaluation = previous.model_copy(
        update={"rules": FileRef(path=rules_path, sha256=sha(rules_raw))}
    )
    (destination / path).write_text(evaluation.model_dump_json(indent=2) + "\n")
    return require_evaluation(destination, evaluation, language=language)


def _write_manifest(package: ScenarioPackage, destination: Path) -> None:
    files = tuple(
        ref.model_copy(update={"sha256": sha((destination / ref.path).read_bytes())})
        for ref in package.bundle.files
        if ref.path not in {RELEASE_PATH, "runtime/evaluation-rules.json"}
    )
    files += tuple(
        FileRef(path=path, sha256=sha((destination / path).read_bytes()))
        for path in (RELEASE_PATH, "runtime/evaluation-rules.json")
    )
    # Scenario revision belongs to authored scenario.yaml and stays byte-for-byte unchanged.
    bundle = package.bundle.model_copy(
        update={
            "files": files,
            "private_files": tuple(
                dict.fromkeys(
                    (*package.bundle.private_files, RELEASE_PATH, "runtime/evaluation-rules.json")
                )
            ),
        }
    )
    (destination / "manifest.json").write_text(bundle.model_dump_json(indent=2) + "\n")


def _verify_copy(
    package: ScenarioPackage,
    candidate: ScenarioPackage,
    before: dict[str, str],
    original_manifest: bytes,
) -> list[str]:
    changed = sorted(
        path for path, value in before.items() if sha((candidate.root / path).read_bytes()) != value
    )
    if set(changed) - GENERATED or content_files(candidate) != content_files(package):
        raise ProtocolError("rebind_authored_content_changed", status=409)
    if (package.root / "manifest.json").read_bytes() != original_manifest or any(
        sha((package.root / path).read_bytes()) != value for path, value in before.items()
    ):
        raise ProtocolError("rebind_source_changed", status=409)
    return changed


def _receipt(
    package: ScenarioPackage,
    candidate: ScenarioPackage,
    release: ReleaseDescription,
    changed: list[str],
) -> dict[str, object]:
    return {
        "source_scenario_hash": package.content_hash,
        "target_scenario_hash": candidate.content_hash,
        "protocol": release.protocol,
        "content_identity": release.content_identity,
        "review": release.review.model_dump(mode="json"),
        "evaluation_version": release.evaluation_version,
        "allowed_generated_files": sorted(GENERATED),
        "changed_generated_files": sorted(
            set(changed) | {RELEASE_PATH, "manifest.json", "runtime/evaluation-rules.json"}
        ),
        "content_files": content_files(candidate),
        "authored_content_unchanged": True,
        "source_unchanged": True,
        "constructor": "passed",
        "work_language": candidate.locale,
        "output": str(candidate.root),
        "accepted": False,
    }


def migrate(
    source: Path,
    destination: Path,
    *,
    contract_revision: str,
    scenario_revision: str,
    runtime_revision: str,
) -> dict[str, object]:
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ProtocolError("rebind_destination_not_fresh", status=409)
    foundation = ROOT / "docs/contracts/expansion-v3/manifest.json"
    if contract_revision != "expansion-v3-" + sha(foundation.read_bytes()):
        raise ProtocolError("rebind_public_manifest_mismatch", status=409)
    package = load_package(source)
    previous = RuntimeBundle.model_validate_json((source / "runtime/bundle.json").read_bytes())
    if not scenario_revision or not runtime_revision or runtime_revision == previous.revision:
        raise ProtocolError("rebind_new_revisions_required", status=409)
    release = describe(package, scenario_revision)
    code = execution_identity()
    if code.commit is None or code.snapshot is None:
        raise ProtocolError("rebind_code_identity_unavailable", status=409)
    before = {ref.path: sha((source / ref.path).read_bytes()) for ref in package.bundle.files}
    original_manifest = (source / "manifest.json").read_bytes()
    _copy_members(package, destination)
    signature = _write_evaluation(destination, package.locale)
    release = release.model_copy(update={"evaluation_signature": signature})
    _write_runtime(destination, previous, release, runtime_revision, code)
    _write_manifest(package, destination)
    candidate = load_package(destination)
    changed = _verify_copy(package, candidate, before, original_manifest)
    from .module import ScenarioModule

    ScenarioModule(destination)
    return _receipt(package, candidate, release, changed)
