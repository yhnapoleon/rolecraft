"""Protocol migration retains bytes, semantic results and historical identities."""

import ast
import importlib.util
import json
from pathlib import Path

import pytest

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.provenance import CodeIdentity
from career_lab.rubrics.v4.feedback import FeedbackEngine
from career_lab.runtime.provenance import require_execution_snapshot
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.rebind import rebind
from career_lab.scenarios.v2.release import (
    GENERATED,
    PROTOCOL,
    ROOT,
    content_files,
    describe,
    sha,
)
from tests.support.scenario_packages import (
    current_contract_revision,
    legacy_matches_current_contract,
)

LEGACY = ROOT / "scenarios/pm_pilot/v2/installed/rubric-v2-a577-2.9.6/pm_pilot"
CASES = json.loads(Path(__file__).with_name("engine-cases.json").read_text())


def complete_feedback_digest(index: int, engine: FeedbackEngine) -> str:
    case = CASES[index]
    packages = tuple(
        C.EvidencePackageV2.model_validate(
            {
                **case["common"],
                **row,
                "rule_context": {**case["common_context"], **row["rule_context"]},
            }
        )
        for row in case["packages"]
    )
    report, diagnostics = engine.evaluate(
        case["session_id"],
        C.ObjectRef.model_validate(case["subject"]),
        C.FileRef.model_validate(case["evaluation"]),
        C.VersionPoint.model_validate(case["as_of"]),
        packages,
        work_language=case["work_language"],
    )
    # Provenance is an additive envelope; every pre-existing result field stays exact.
    result = {
        "report": report.model_dump(mode="json", exclude={"provenance"}),
        "diagnostics": diagnostics,
    }
    return C.digest(result)


@pytest.mark.parametrize("index", range(len(CASES)))
def test_complete_feedback_semantics_match_original_execution(index: int) -> None:
    assert complete_feedback_digest(index, FeedbackEngine()) == CASES[index]["expected_digest"], (
        "evaluation version change required"
    )


@pytest.mark.parametrize(
    ("filename", "field", "accepted_digest"),
    [
        (
            "feedback-baseline.json",
            "comparison_baseline_sha256",
            "800d1c602bf84cdf0adb482cdcbefdb25bfe604daf1c6485cfacddf1af7a8464",
        ),
        (
            "engine-cases.json",
            "engine_baseline_sha256",
            "7b9d79e92355e98f1160f35219ac104bdc90bd05a32edfeb484adf68da21f891",
        ),
    ],
)
def test_registered_comparison_evidence_is_immutable(
    filename: str, field: str, accepted_digest: str
) -> None:
    registry = json.loads((ROOT / "configs/evaluation/versions.json").read_text())
    entry = registry["versions"]["feedback-rubric-v2-c2.1"]
    assert entry[field] == accepted_digest, "existing evaluation version cannot be rewritten"
    assert sha(Path(__file__).with_name(filename).read_bytes()) == entry[field], (
        "evaluation version change required"
    )


def test_changed_evaluation_output_requires_a_new_version(tmp_path: Path) -> None:
    # Execute a real source mutant: coverage is inverted for the same fixed inputs.
    source = ROOT / "src/career_lab/rubrics/v4/feedback.py"
    original = source.read_text()
    tree = ast.parse(original)
    targets = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg == "verified_coverage"
    ]
    assert len(targets) == 1, "coverage mutation must target one real implementation expression"
    targets[0].value = ast.parse("0 if verified else 1", mode="eval").body
    changed = ast.unparse(tree)
    assert ast.dump(ast.parse(changed)) != ast.dump(ast.parse(original))
    path = tmp_path / "feedback_mutant.py"
    path.write_text(changed)
    spec = importlib.util.spec_from_file_location("career_lab.rubrics.v4.feedback_mutant", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(AssertionError, match="evaluation version change required"):
        assert (
            complete_feedback_digest(0, module.FeedbackEngine()) == CASES[0]["expected_digest"]
        ), "evaluation version change required"


def test_required_provenance_is_rejected_by_protocol_compatibility() -> None:
    from career_lab.contracts.v2.compatibility import without_provenance

    schema = {"title": "FeedbackV2", "properties": {"provenance": {}}, "required": ["provenance"]}
    with pytest.raises(C.ProtocolError, match="provenance must remain optional"):
        without_provenance(schema)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_formal_protocol_migration_preserves_each_business_file_and_old_release(
    tmp_path: Path, language: str
) -> None:
    source = LEGACY if language == "zh" else LEGACY / "locales/en"
    package = load_package(source)
    before = describe(package, "candidate")
    target = tmp_path / "candidate"
    revision = "expansion-v3-" + sha(
        (ROOT / "docs/contracts/expansion-v3/manifest.json").read_bytes()
    )
    result = rebind(
        source,
        target,
        protocol=PROTOCOL,
        contract_revision=revision,
        scenario_revision="protocol-v1",
        runtime_revision="protocol-v1",
    )
    module = ScenarioModule(target)
    assert module.release is not None
    assert module.release.content_identity == before.content_identity
    assert module.release.review == before.review
    assert module.release.original_release_identity == package.content_hash
    assert content_files(module.package) == content_files(package)
    assert set(result["changed_generated_files"]) <= GENERATED
    assert (target / "scenario.yaml").read_bytes() == (source / "scenario.yaml").read_bytes()
    assert load_package(source).content_hash == package.content_hash
    assert module.package.bundle.revision == package.bundle.revision


def test_implementation_layout_does_not_change_content_or_review_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from career_lab.scenarios.v2 import localization

    before = describe(load_package(LEGACY), "before")
    released = tmp_path / "released"
    rebind(
        LEGACY,
        released,
        protocol=PROTOCOL,
        contract_revision=current_contract_revision(),
        scenario_revision="protocol-v1",
        runtime_revision="protocol-v1",
    )
    # The legacy runtime can only be constructed while its pinned contract is current.
    roots = [released]
    if legacy_matches_current_contract(LEGACY):
        roots.append(LEGACY)

    # The old source-layout function must never be consulted by either protocol's runtime.
    def moved_implementation(*_args: object) -> dict[str, str]:
        raise AssertionError("Implementation file layout is not a content admission condition")

    monkeypatch.setattr(localization, "runtime_source_files", moved_implementation)
    for root in roots:
        after = describe(ScenarioModule(root).package, "after")
        assert after.content_identity == before.content_identity
        assert after.review == before.review


def test_business_file_edit_changes_content_identity_and_invalidates_old_review(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    package = load_package(LEGACY)
    original = content_files(package)
    for ref in package.bundle.files:
        target = tmp_path / ref.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((package.root / ref.path).read_bytes())
    changed_path = "materials/brief-v1.md"
    (tmp_path / changed_path).write_bytes(
        (tmp_path / changed_path).read_bytes() + b"\nChanged deadline.\n"
    )
    files = tuple(
        ref.model_copy(update={"sha256": sha((tmp_path / ref.path).read_bytes())})
        for ref in package.bundle.files
    )
    altered = replace(
        package, root=tmp_path, bundle=package.bundle.model_copy(update={"files": files})
    )
    assert C.digest(content_files(altered)) != C.digest(original)
    from career_lab.scenarios.v2.release import RELEASE_PATH, read_release

    release = describe(package, "candidate")
    (tmp_path / RELEASE_PATH).write_text(release.model_dump_json())
    release_ref = C.FileRef(path=RELEASE_PATH, sha256=sha((tmp_path / RELEASE_PATH).read_bytes()))
    altered = replace(
        altered,
        bundle=altered.bundle.model_copy(update={"files": (*altered.bundle.files, release_ref)}),
    )
    with pytest.raises(C.ProtocolError, match="release content mismatch"):
        read_release(altered)


def test_feedback_generation_requires_restart_after_code_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from career_lab.runtime import provenance

    monkeypatch.setattr(provenance, "source_snapshot", lambda _root: "new-snapshot")
    with pytest.raises(C.ProtocolError, match="execution restart required"):
        require_execution_snapshot(
            CodeIdentity(status="modified", commit="1" * 40, snapshot="old-snapshot")
        )


def test_old_feedback_missing_provenance_is_not_relabelled() -> None:
    case = CASES[0]
    old = {
        "schema_version": 2,
        "id": "historic-feedback",
        "session_id": case["session_id"],
        "subject": case["subject"],
        "evaluation": case["evaluation"],
        "as_of": case["as_of"],
        "items": [],
        "business_response": "Recorded response",
        "next_options": [],
        "verified_coverage": 0,
        "model_coverage": 0,
    }
    # Use only the preserved record; decoding must not inspect the current Git identity.
    decoded = C.FeedbackV2.model_validate(old)
    assert decoded.provenance is None
    assert "provenance" not in old
    assert "provenance" not in decoded.model_dump(mode="json")
    assert decoded.id == old["id"]
    assert decoded.evaluation.model_dump(mode="json") == case["evaluation"]
