"""The approved final rubric is loadable only as its exact registered bytes and semantics."""

import hashlib
import json
from pathlib import Path

import pytest

from career_lab.contracts import v2 as C
from career_lab.rubrics.evaluation_identity import FINAL_EVALUATION_VERSION, REGISTRY
from career_lab.rubrics.v4.final_rubric import (
    FINAL_RUBRIC_REVISION,
    final_definition_bytes,
    final_policies,
    load_final_definition,
)
from career_lab.rubrics.v4.rubric_v2 import (
    CRITERIA,
    final_rules_document,
    install_candidate,
    installed_final_policies,
    load_installed_policies,
    policies,
)
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.release import evaluation_signature
from career_lab.scenarios.v2.release_migration import _copy_members, _write_final_evaluation

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scenarios/pm_pilot/v2/candidates/semantic-rules-v1-2.9.6"
FINAL_SHA256 = "aa0de4302ca42368a262dc516fd3d8dab83286dd10dff7350c35b0c3772321cd"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_final_policies_carry_final_conditions_and_candidate_rule_flags(language: str) -> None:
    final = final_policies(work_language=language)
    candidate = policies(work_language=language)
    definition = load_final_definition("aipm")
    assert [p.id for p in final] == [p.id for p in candidate]
    titles = [(zh + "。", en + ".") for _, zh, en, _, _ in CRITERIA]
    for policy, earlier, row, title in zip(
        final, candidate, definition["criteria"], titles, strict=True
    ):
        assert policy.description == row[language]["description"]
        assert policy.description != earlier.description
        # The item title is unchanged; only the conditions after it are final.
        expected = title[language == "en"]
        assert policy.description.split("\n")[0] == expected
        assert earlier.description.startswith(expected)
        assert (policy.mechanism, policy.purposes, policy.launch_only) == (
            earlier.mechanism,
            earlier.purposes,
            earlier.launch_only,
        )
    assert installed_final_policies(work_language=language) == final


def test_final_definition_bytes_are_the_approved_file() -> None:
    assert hashlib.sha256(final_definition_bytes()).hexdigest() == FINAL_SHA256
    rules = final_rules_document()
    assert rules["evaluation_version"] == FINAL_EVALUATION_VERSION
    assert rules["rubric_revision"] == FINAL_RUBRIC_REVISION
    assert rules["revision"] == "rules-v4-rubric-v2-c2"


@pytest.mark.parametrize(
    ("package", "language"),
    [
        ("pm_pilot", "zh"),
        ("pm_pilot/locales/en", "en"),
        ("pm_pilot_urgent", "zh"),
        ("pm_pilot_capacity15/locales/en", "en"),
    ],
)
def test_registered_final_signature_is_computed_from_the_definition(
    tmp_path: Path, package: str, language: str
) -> None:
    source = load_package(SOURCE / package)
    destination = tmp_path / "copy"
    _copy_members(source, destination)
    bundle = _write_final_evaluation(destination, language)
    entry = json.loads(REGISTRY.read_text())["versions"][FINAL_EVALUATION_VERSION]
    assert entry["rubric"] == {"revision": FINAL_RUBRIC_REVISION, "sha256": FINAL_SHA256}
    assert entry["protocol_signatures"][language] == [evaluation_signature(destination, bundle)]
    assert bundle.revision == FINAL_RUBRIC_REVISION
    assert (destination / bundle.rubric.path).read_bytes() == final_definition_bytes()


def write_bundle(root: Path, rubric: bytes, rules: bytes) -> C.FileRef:
    (root / "rubric.json").write_bytes(rubric)
    (root / "rules.json").write_bytes(rules)
    bundle = C.EvaluationBundle(
        id="w05-rubric-v2",
        revision="test",
        rubric=C.FileRef(path="rubric.json", sha256=hashlib.sha256(rubric).hexdigest()),
        rules=C.FileRef(path="rules.json", sha256=hashlib.sha256(rules).hexdigest()),
        graders=(),
        protocol=C.FileRef(path="rules.json", sha256=hashlib.sha256(rules).hexdigest()),
    )
    body = bundle.model_dump_json().encode()
    (root / "evaluation.json").write_bytes(body)
    return C.FileRef(path="evaluation.json", sha256=hashlib.sha256(body).hexdigest())


@pytest.mark.parametrize("language", ["zh", "en"])
def test_installed_loader_selects_final_or_candidate_by_bound_rubric(
    tmp_path: Path, language: str
) -> None:
    rules = (C.canonical(final_rules_document()) + "\n").encode()
    ref = write_bundle(tmp_path, final_definition_bytes(), rules)
    assert load_installed_policies(tmp_path, ref, work_language=language) == final_policies(
        work_language=language
    )
    candidate = tmp_path / "candidate"
    refs = install_candidate(candidate)
    ref = write_bundle(
        candidate,
        (candidate / refs["rubric"].path).read_bytes(),
        (candidate / refs["rules"].path).read_bytes(),
    )
    assert load_installed_policies(candidate, ref, work_language=language) == policies(
        work_language=language
    )


def test_altered_final_rubric_or_mismatched_rules_are_rejected(tmp_path: Path) -> None:
    rules = (C.canonical(final_rules_document()) + "\n").encode()
    altered = final_definition_bytes().replace(b'"status": "final"', b'"status":  "final"')
    assert altered != final_definition_bytes()
    with pytest.raises(C.ProtocolError, match="rubric candidate version mismatch"):
        load_installed_policies(tmp_path, write_bundle(tmp_path, altered, rules))
    candidate_rules = json.loads(rules)
    candidate_rules["evaluation_version"] = "feedback-rubric-v2-c2.1"
    with pytest.raises(C.ProtocolError, match="rubric candidate version mismatch"):
        load_installed_policies(
            tmp_path,
            write_bundle(
                tmp_path,
                final_definition_bytes(),
                (C.canonical(candidate_rules) + "\n").encode(),
            ),
        )
