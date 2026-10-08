"""Protocol migration retains bytes, semantic results and historical identities."""

import json
from pathlib import Path

import pytest

from career_lab.contracts import v2 as C
from career_lab.contracts.v2.provenance import CodeIdentity, require_execution_snapshot
from career_lab.rubrics.v4.feedback import FeedbackEngine
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.module import ScenarioModule
from career_lab.scenarios.v2.rebind import rebind
from career_lab.scenarios.v2.release import (
    EVALUATION_VERSION,
    GENERATED,
    PROTOCOL,
    ROOT,
    content_files,
    describe,
    require_behavior,
    sha,
)

LEGACY = ROOT / "scenarios/pm_pilot/v2/installed/rubric-v2-a577-2.9.6/pm_pilot"
CASES = json.loads(Path(__file__).with_name("engine-cases.json").read_text())


@pytest.mark.parametrize("index", range(len(CASES)))
def test_complete_feedback_semantics_match_original_execution(index: int) -> None:
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
    report, diagnostics = FeedbackEngine().evaluate(
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
    require_behavior(
        EVALUATION_VERSION, C.digest(result), {EVALUATION_VERSION: case["expected_digest"]}
    )


def test_changed_evaluation_output_requires_a_new_version() -> None:
    expected = {EVALUATION_VERSION: CASES[0]["expected_digest"]}
    changed = C.digest({"items": [{"label": "MET", "source": "verified_rule"}]})
    with pytest.raises(C.ProtocolError, match="evaluation version change required"):
        require_behavior(EVALUATION_VERSION, changed, expected)
    # Registering a distinct version and its own accepted evidence is the explicit path.
    expected["candidate-new-semantics"] = changed
    require_behavior("candidate-new-semantics", changed, expected)


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from career_lab.scenarios.v2 import localization

    before = describe(load_package(LEGACY), "before")

    # The old source-layout function must never be consulted by either protocol's runtime.
    def moved_implementation(*_args: object) -> dict[str, str]:
        raise AssertionError("Implementation file layout is not a content admission condition")

    monkeypatch.setattr(localization, "runtime_source_files", moved_implementation)
    module = ScenarioModule(LEGACY)
    after = describe(module.package, "after")
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
    from career_lab.contracts.v2 import provenance

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
