"""The formal rebind installs the final rubric through generated files; content is unchanged."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts import v2 as C
from career_lab.rubrics.evaluation_identity import EVALUATION_VERSION, FINAL_EVALUATION_VERSION
from career_lab.rubrics.v4.final_rubric import final_definition_bytes, final_policies
from career_lab.rubrics.v4.rubric_v2 import load_installed_policies
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.rebind import rebind
from career_lab.scenarios.v2.release import (
    GENERATED,
    PROTOCOL,
    ROOT,
    content_files,
    read_release,
    sha,
)
from career_lab.scenarios.v2.release_migration import migrate
from tests.support.scenario_packages import current_contract_revision

from .conftest import PublishedSession
from .test_published_catalog import submit

# The previous installation stays in the repository as history and as the rebind source.
SOURCE = ROOT / "scenarios/pm_pilot/v2/candidates/semantic-rules-v1-2.9.6"
FINAL = "rubric-v2-final-20261009"
FINAL_SHA256 = "aa0de4302ca42368a262dc516fd3d8dab83286dd10dff7350c35b0c3772321cd"
LANGUAGE_ROOTS = {"zh": "pm_pilot", "en": "pm_pilot/locales/en"}


def members(root: Path) -> dict[str, str]:
    package = load_package(root)
    return {ref.path: sha((root / ref.path).read_bytes()) for ref in package.bundle.files}


@pytest.mark.parametrize("language", ["zh", "en"])
def test_formal_cli_installs_final_rubric_without_changing_content(
    tmp_path: Path, language: str
) -> None:
    source = SOURCE / LANGUAGE_ROOTS[language]
    before = members(source)
    destination = tmp_path / "candidate"
    command = [
        sys.executable,
        "-m",
        "career_lab.scenarios.v2.rebind",
        "--source",
        str(source),
        "--output",
        str(destination),
        "--protocol",
        PROTOCOL,
        "--evaluation",
        FINAL,
        "--scenario-revision",
        "rubric-final-test",
        "--runtime-revision",
        "rubric-final-test",
        "--contract-revision",
        current_contract_revision(),
        "--smoke-database",
        str(tmp_path / "smoke.db"),
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert members(source) == before, "the source package must not change"
    original, candidate = load_package(source), load_package(destination)
    after = members(destination)
    assert content_files(candidate) == content_files(original)
    for path, digest in before.items():
        if path not in GENERATED:
            assert after[path] == digest, path
    assert {p for p in before if after.get(p) != before[p]} <= GENERATED
    assert set(after) - set(before) == {"runtime/evaluation-rubric.json"}
    assert after["runtime/evaluation-rubric.json"] == FINAL_SHA256
    old_release, new_release = read_release(original), read_release(candidate)
    assert old_release is not None and new_release is not None
    assert new_release.content_identity == old_release.content_identity
    assert new_release.review == old_release.review
    assert new_release.original_release_identity == old_release.original_release_identity
    assert old_release.evaluation_version == EVALUATION_VERSION
    assert new_release.evaluation_version == FINAL_EVALUATION_VERSION
    evaluation_ref = next(r for r in candidate.bundle.files if r.path == "runtime/evaluation.json")
    evaluation = C.EvaluationBundle.model_validate_json(
        (destination / "runtime/evaluation.json").read_bytes()
    )
    assert evaluation.revision == FINAL and evaluation.mode == "advisory"
    assert evaluation.rubric.path == "runtime/evaluation-rubric.json"
    rules = json.loads((destination / evaluation.rules.path).read_bytes())
    assert rules["evaluation_version"] == FINAL_EVALUATION_VERSION
    assert rules["revision"] == "rules-v4-rubric-v2-c2"
    assert rules["rubric_revision"] == FINAL
    assert load_installed_policies(
        destination, evaluation_ref, work_language=language
    ) == final_policies(work_language=language)
    smoke = json.loads((tmp_path / "candidate-verification/rebind.json").read_text())
    assert (
        smoke["authored_content_unchanged"] and smoke["http_startup"]["work_language"] == language
    )


def test_rebind_without_evaluation_keeps_the_source_evaluation(tmp_path: Path) -> None:
    source = SOURCE / "pm_pilot"
    destination = tmp_path / "candidate"
    rebind(
        source,
        destination,
        protocol=PROTOCOL,
        contract_revision=current_contract_revision(),
        scenario_revision="same-evaluation",
        runtime_revision="same-evaluation",
    )
    assert not (destination / "runtime/evaluation-rubric.json").exists()
    for path in ("runtime/evaluation-rules.json", "runtime/evaluation-protocol.json"):
        assert (destination / path).read_bytes() == (source / path).read_bytes()
    assert (destination / "runtime/evaluation.json").read_bytes() == (
        source / "runtime/evaluation.json"
    ).read_bytes()
    release = read_release(load_package(destination))
    assert release is not None and release.evaluation_version == EVALUATION_VERSION


def test_evaluation_replacement_requires_the_release_protocol_and_a_known_target(
    tmp_path: Path,
) -> None:
    with pytest.raises(C.ProtocolError, match="release protocol unsupported"):
        rebind(
            SOURCE / "pm_pilot",
            tmp_path / "legacy-path",
            contract_revision=current_contract_revision(),
            scenario_revision="x",
            runtime_revision="x",
            evaluation=FINAL,
        )
    with pytest.raises(C.ProtocolError, match="evaluation version unsupported"):
        migrate(
            SOURCE / "pm_pilot",
            tmp_path / "unknown",
            contract_revision=current_contract_revision(),
            scenario_revision="x",
            runtime_revision="x",
            evaluation="rubric-v2-unapproved",
        )
    assert not (tmp_path / "legacy-path").exists() and not (tmp_path / "unknown").exists()


def feedback_for(root: Path, directory: Path, language: str) -> dict[str, object]:
    app = create_runtime_app(
        "sqlite:///" + str(directory / "session.db"), provider="local", scenario_root=root
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
            )
            assert response.status_code == 200, response.text
            created = response.json()
            session = PublishedSession(
                app,
                client,
                created["session_id"],
                {"Authorization": "Bearer " + created["token"]},
                language,
            )
            _, feedback = submit(session)
            return feedback
    finally:
        app.state.store.close()
        app.state.v2_store.db.engine.dispose()


def learner_visible(feedback: dict[str, object]) -> object:
    rows = [
        {
            key: item.get(key)
            for key in (
                "criterion",
                "label",
                "applicability",
                "source",
                "explanation",
                "rule_bound",
            )
        }
        for name in ("items", "rule_items")
        for item in feedback.get(name) or []
    ]
    return {
        "rows": rows,
        "business_response": feedback["business_response"],
        "next_options": feedback["next_options"],
        "coverage": (feedback["verified_coverage"], feedback["model_coverage"]),
        "facts": [s.get("summary") for s in feedback.get("verified_facts") or []],
    }


@pytest.mark.parametrize("language", ["zh", "en"])
def test_same_submission_feedback_differs_only_in_evaluation_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    monkeypatch.delenv("CAREER_LAB_SCENARIO_CATALOG", raising=False)
    monkeypatch.delenv("CAREER_LAB_SCENARIO_V2", raising=False)
    source = SOURCE / LANGUAGE_ROOTS[language]
    final = tmp_path / "final-package"
    rebind(
        source,
        final,
        protocol=PROTOCOL,
        contract_revision=current_contract_revision(),
        scenario_revision="rubric-final-test",
        runtime_revision="rubric-final-test",
        evaluation=FINAL,
    )
    results = {}
    for name, root in (("candidate", source), ("final", final)):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setenv("CAREER_LAB_SCENARIO_ARCHIVE", str(directory / "archive"))
        results[name] = feedback_for(root, directory, language)
    old, new = results["candidate"], results["final"]
    assert old["provenance"]["evaluation_version"] == EVALUATION_VERSION
    assert new["provenance"]["evaluation_version"] == FINAL_EVALUATION_VERSION
    assert old["provenance"]["rules_version"] == new["provenance"]["rules_version"]
    assert old["evaluation"] != new["evaluation"]
    assert (
        new["evaluation"]["sha256"]
        == hashlib.sha256((final / "runtime/evaluation.json").read_bytes()).hexdigest()
    )
    assert len(new["items"]) == 14
    assert learner_visible(new) == learner_visible(old)
    assert final_definition_bytes() == (final / "runtime/evaluation-rubric.json").read_bytes()
