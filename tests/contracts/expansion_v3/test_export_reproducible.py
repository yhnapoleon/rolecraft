"""Current-tree exports are deterministic and retain all publication history."""

import hashlib
import json
import re
import shutil
from pathlib import Path

from career_lab.contracts.v2.export import export
from scripts.regression.compare import protected_changes

ROOT = Path(__file__).resolve().parents[3]
FREEZE = ROOT / "docs/contracts/expansion-v3"
# These complete fields are computed from production code/current inputs, not publication history.
# schemas includes owner/consumer/test references plus live schema/example hashes;
# consumer_interfaces and request_payloads are generated registries. revision is a return value.
COMPUTED_FIELDS = {
    "source_files",
    "documents",
    "errors",
    "schemas",
    "openapi",
    "consumer_interfaces",
    "request_payloads",
    "revision",
}
DOCUMENTS = ("compatibility.md", "module-interfaces.md", "consumer-request-resolution.json")
# The original, approved non-contract implementation scope. Contract modules are discovered below.
IMPLEMENTATION_INPUTS = (
    "src/career_lab/api/app.py",
    "src/career_lab/api/v4_extensions.py",
    "src/career_lab/cli.py",
    "src/career_lab/api/vertical_runtime.py",
    "src/career_lab/api/vertical_reads.py",
    "src/career_lab/api/v4_config.py",
    "src/career_lab/api/public_materials.py",
    "src/career_lab/api/lifecycle_integration.py",
    "src/career_lab/api/evaluation_runtime.py",
    "src/career_lab/api/workspace_integration.py",
    "src/career_lab/api/feedback_integration.py",
    "src/career_lab/api/role_snapshot.py",
    "src/career_lab/runtime/role_snapshot.py",
    "src/career_lab/api/private_roles.py",
    "src/career_lab/api/modules.py",
    "src/career_lab/api/v2_routes.py",
    "src/career_lab/storage/v2_tables.py",
    "src/career_lab/storage/v2_store.py",
    "src/career_lab/storage/v2_jobs.py",
    "src/career_lab/storage/v2_snapshot.py",
    "src/career_lab/storage/v2_lifecycle.py",
    "src/career_lab/storage/v2_remap.py",
    "src/career_lab/jobs/worker.py",
    "src/career_lab/jobs/repository.py",
    "src/career_lab/rubrics/registry.py",
    "src/career_lab/storage/object_plans.py",
    "src/career_lab/storage/reference_graph.py",
    "src/career_lab/storage/record_invariants.py",
)


def source_paths(root: Path) -> set[Path]:
    return set((root / "src/career_lab/contracts").rglob("*.py")) | {
        root / name for name in IMPLEMENTATION_INPUTS
    }


def exported_bytes(output: Path) -> dict[str, bytes]:
    return {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }


def test_export_is_byte_deterministic(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    export(ROOT, first)
    export(ROOT, second)
    before, after = exported_bytes(first), exported_bytes(second)
    differences = [
        name for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)
    ]
    assert not differences, "Nondeterministic generated files: " + ", ".join(differences)


def test_export_preserves_publication_history(tmp_path: Path) -> None:
    export(ROOT, tmp_path)
    generated = json.loads((tmp_path / "manifest.json").read_text())
    frozen = json.loads((FREEZE / "manifest.json").read_text())
    assert {k: v for k, v in generated.items() if k not in COMPUTED_FIELDS} == {
        k: v for k, v in frozen.items() if k not in COMPUTED_FIELDS
    }
    assert generated["documents"] == {
        name: {"path": name, "sha256": hashlib.sha256((FREEZE / name).read_bytes()).hexdigest()}
        for name in DOCUMENTS
    }
    assert generated["source_files"] == {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_paths(ROOT)
    }


def test_export_error_codes_cover_current_source_scope(tmp_path: Path) -> None:
    export(ROOT, tmp_path)
    codes = set(json.loads((tmp_path / "errors.json").read_text())["codes"])
    scanned = {
        code
        for path in source_paths(ROOT)
        for code in re.findall(r"ProtocolError\(['\"]([^'\"]+)", path.read_text())
    }
    # This is a compatibility/export-time invariant, never an HTTP response code.
    internal_codes = {"provenance_must_remain_optional"}
    assert scanned - internal_codes <= codes, sorted(scanned - internal_codes - codes)
    assert "credential_derivation_unavailable" in codes
    assert not codes & internal_codes


def test_export_calculates_inputs_from_selected_root(tmp_path: Path) -> None:
    selected_root = tmp_path / "checkout"
    for path in source_paths(ROOT):
        target = selected_root / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    document_root = selected_root / "docs/contracts/expansion-v3"
    document_root.mkdir(parents=True)
    for name in DOCUMENTS:
        (document_root / name).write_text("Selected checkout: " + name)
    (document_root / "errors.json").write_text(json.dumps({"codes": ["historical_only_error"]}))
    changed_source = selected_root / "src/career_lab/api/v4_extensions.py"
    with changed_source.open("a") as stream:
        stream.write("\nraise ProtocolError('new_public_error')\n")
    output = tmp_path / "export"
    export(selected_root, output)
    generated = json.loads((output / "manifest.json").read_text())
    assert generated["documents"] == {
        name: {
            "path": name,
            "sha256": hashlib.sha256((document_root / name).read_bytes()).hexdigest(),
        }
        for name in DOCUMENTS
    }
    assert generated["source_files"][changed_source.relative_to(selected_root).as_posix()] == (
        hashlib.sha256(changed_source.read_bytes()).hexdigest()
    )
    codes = set(json.loads((output / "errors.json").read_text())["codes"])
    assert {"historical_only_error", "new_public_error"} <= codes


def test_frozen_release_files_remain_unchanged() -> None:
    assert protected_changes() == []
