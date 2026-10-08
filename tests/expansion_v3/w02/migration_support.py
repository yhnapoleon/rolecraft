"""W02 release-migration preparation; outside the frozen runtime source set.

Never installs public code or bypasses pins. Only stages a new candidate under
an already installed coordinator-authorized immutable public input.
"""

import hashlib
import json
from pathlib import Path
import re
import yaml

from career_lab.contracts.v2 import (
    AssistantConfig,
    FactV2,
    MaterialV2,
    RoleSpecV2,
    RuntimeBundle,
    ScenarioBundle,
    FileRef,
    ProtocolError,
)
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.seed import build_seed

CONSUMED_MODELS = (
    "ActionInput",
    "ApprovalInput",
    "AssistantConfig",
    "AuthContext",
    "BusinessBasis",
    "BusinessDecision",
    "BusinessRequest",
    "Command",
    "DisclosurePolicy",
    "EffectiveConfig",
    "EvaluationBundle",
    "EvidenceRefV2",
    "Executor",
    "ExternalReference",
    "FactV2",
    "FileRef",
    "MaterialV2",
    "ObjectRef",
    "PublicEvent",
    "ResourcePage",
    "RetrievedChunk",
    "RoleSpecV2",
    "RuntimeBundle",
    "ScenarioBundle",
    "ScenarioStateV2",
    "SessionBindings",
    "SourceFragment",
    "SourceIdentity",
    "TestExecutionMetadata",
    "TestRequestV2",
    "TestResultV2",
    "VersionPoint",
    "WorldStateV2",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def contract_manifest(path, expected_revision):
    if not re.fullmatch(r"expansion-v3-[0-9a-f]{64}", expected_revision):
        raise ProtocolError("migration_revision_invalid")
    raw = Path(path).read_bytes()
    if "expansion-v3-" + sha(raw) != expected_revision:
        raise ProtocolError("migration_manifest_mismatch", status=409)
    data = json.loads(raw)
    if not isinstance(data.get("schemas"), dict) or not isinstance(data.get("source_files"), dict):
        raise ProtocolError("migration_manifest_invalid")
    return raw, data


def inspect_transition(source_root, current_manifest, candidate_manifest, expected_revision):
    source = load_package(source_root)
    old = json.loads(Path(current_manifest).read_bytes())
    new_raw, new = contract_manifest(candidate_manifest, expected_revision)
    binding = json.loads((Path(source_root) / "runtime/source-files.json").read_bytes())
    current_hash = sha(Path(current_manifest).read_bytes())
    if binding["foundation_contract_sha256"] != current_hash:
        raise ProtocolError("current_runtime_input_mismatch", status=409)
    changed = []
    for name in CONSUMED_MODELS:
        if name not in old["schemas"] or name not in new["schemas"]:
            raise ProtocolError("migration_consumed_schema_missing")
        if old["schemas"][name]["schema_sha256"] != new["schemas"][name]["schema_sha256"]:
            changed.append(name)
    return {
        "source_bundle_hash": source.content_hash,
        "bound_foundation_hash": binding["foundation_contract_sha256"],
        "candidate_foundation_hash": sha(new_raw),
        "requires_rebuild": binding["foundation_contract_sha256"] != sha(new_raw),
        "changed_consumed_schemas": changed,
        "changed_public_implementations": sorted(
            path
            for path in old["source_files"].keys() | new["source_files"].keys()
            if old["source_files"].get(path) != new["source_files"].get(path)
        ),
        "schema_equality_is_semantic_compatibility": False,
        "semantic_compatibility_verified": False,
        "public_input_installed": False,
    }


def _normalized_file(root, name, model):
    value = json.loads((Path(root) / name).read_bytes())
    if isinstance(value, list):
        return [model.model_validate(x).model_dump(mode="json") for x in value]
    return model.model_validate(value).model_dump(mode="json")


def stage_registered_migration(
    source_root, destination, *, expected_revision, scenario_revision, runtime_revision
):
    """Rebuild under the already installed, coordinator-authorized public input.

    Caller must first consume the exact immutable input via update-context. This
    helper only verifies that precondition and writes a NEW owned candidate.
    Regression and review still decide whether it may be used.
    """
    source_root = Path(source_root).resolve()
    destination = Path(destination)
    if destination.exists():
        raise ProtocolError("migration_destination_exists", status=409)
    if destination.resolve().is_relative_to(source_root):
        raise ProtocolError("migration_destination_inside_source", status=409)
    old = load_package(source_root)
    previous_runtime = RuntimeBundle.model_validate_json(
        (source_root / "runtime/bundle.json").read_bytes()
    )
    if not scenario_revision or scenario_revision == old.bundle.revision:
        raise ProtocolError("migration_requires_new_scenario_revision")
    if not runtime_revision or runtime_revision == previous_runtime.revision:
        raise ProtocolError("migration_requires_new_runtime_revision")
    repo = Path(__file__).resolve().parents[3]
    installed = repo / "docs/contracts/expansion-v3/manifest.json"
    contract_manifest(installed, expected_revision)
    case_path = source_root / "research/public-case-records.json"
    cases = json.loads(case_path.read_bytes()) if case_path.is_file() else None
    # This is the real renderer, not a hash substitution in an old manifest.
    build_seed(destination, cases)
    # Business data must not silently change during an input-only migration.
    for filename, model in [
        ("baseline.json", AssistantConfig),
        ("facts.json", FactV2),
        ("materials.json", MaterialV2),
        ("roles.json", RoleSpecV2),
    ]:
        if _normalized_file(source_root, filename, model) != _normalized_file(
            destination, filename, model
        ):
            raise ProtocolError("migration_business_content_changed", status=409)
    for filename in (
        "probes.json",
        "paths.json",
        "decision_examples.json",
        "rubric-reference.json",
    ):
        if json.loads((source_root / filename).read_bytes()) != json.loads(
            (destination / filename).read_bytes()
        ):
            raise ProtocolError("migration_authoring_data_changed", status=409)
    if (
        cases is not None
        and (destination / "research/public-case-records.json").read_bytes()
        != case_path.read_bytes()
    ):
        raise ProtocolError("migration_case_history_changed", status=409)
    rules_path = destination / "scenario.yaml"
    rules = yaml.safe_load(rules_path.read_text())
    old_rules = yaml.safe_load((source_root / "scenario.yaml").read_text())
    if {k: v for k, v in rules.items() if k != "revision"} != {
        k: v for k, v in old_rules.items() if k != "revision"
    }:
        raise ProtocolError("migration_business_rules_changed", status=409)
    generated = ScenarioBundle.model_validate_json((destination / "manifest.json").read_bytes())
    if generated.model_dump(exclude={"revision", "files"}) != old.bundle.model_dump(
        exclude={"revision", "files"}
    ):
        raise ProtocolError("migration_scenario_contract_changed", status=409)
    rules["revision"] = scenario_revision
    rules_path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=True))
    runtime_path = destination / "runtime/bundle.json"
    runtime = RuntimeBundle.model_validate_json(runtime_path.read_bytes()).model_copy(
        update={"revision": runtime_revision}
    )
    runtime_path.write_text(runtime.model_dump_json(indent=2) + "\n")
    migration_record = {
        "previous_bundle_hash": old.content_hash,
        "previous_runtime_hash": sha((source_root / "runtime/bundle.json").read_bytes()),
        "previous_foundation_hash": json.loads(
            (source_root / "runtime/source-files.json").read_bytes()
        )["foundation_contract_sha256"],
        "target_contract_revision": expected_revision,
        "scenario_revision": scenario_revision,
        "runtime_revision": runtime_revision,
        "semantic_regression_required": True,
        "compatibility_approved": False,
        "case_records_preserved": cases is not None,
    }
    # The provenance report stays with delivery evidence. The runtime package is
    # reproducible directly from the actual renderer and preserved case history.
    paths = {ref.path for ref in generated.files}
    updated = generated.model_copy(
        update={
            "revision": scenario_revision,
            "files": tuple(
                FileRef(
                    path=path,
                    sha256=sha((destination / path).read_bytes()),
                    media_type=next(
                        (r.media_type for r in generated.files if r.path == path),
                        "application/json",
                    ),
                )
                for path in sorted(paths)
            ),
        }
    )
    (destination / "manifest.json").write_text(updated.model_dump_json(indent=2) + "\n")
    # Real constructor checks code, schema data, exact input and all file hashes.
    module = ScenarioModule(destination)
    return {
        **migration_record,
        "candidate_bundle_hash": module.package.content_hash,
        "candidate_constructor": "passed",
        "candidate_installed": False,
        "required_next_checks": [
            "ScenarioModule→Gateway→SQLite constructor/create",
            "refresh→new policy test persistence",
            "exact historical references",
            "read request recovery",
            "permission/idempotency/failure rollback",
            "independent review",
        ],
    }
