"""Evaluation identity survives formatting while preserving installed feedback."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.scenarios.v2.release import ROOT

from .conftest import PublishedSession
from .test_published_catalog import submit

RULE_MODULES = (
    "rubric_v2.py",
    "applicability.py",
    "rules_v2.py",
    "rules.py",
    "feedback.py",
    "judge.py",
    "support.py",
    "provider.py",
)
LEGACY_CATALOG = ROOT / "tests/regression/published-catalog-legacy.json"


def exercise_feedback(catalog: Path, directory: Path) -> None:
    """Use production HTTP, SQLite and worker for each immutable installed package."""
    rows = json.loads(catalog.read_text())["scenarios"]
    from career_lab.contracts import v2 as C
    from career_lab.rubrics.v4.rubric_v2 import load_installed_policies

    for index, row in enumerate(rows):
        root = ROOT / row["root"]
        manifest = json.loads((root / "manifest.json").read_text())
        evaluation = next(
            ref for ref in manifest["files"] if ref["path"] == "runtime/evaluation.json"
        )
        assert (
            len(
                load_installed_policies(
                    root, C.FileRef.model_validate(evaluation), work_language=row["work_language"]
                )
            )
            == 14
        )
        os.environ.pop("CAREER_LAB_SCENARIO_CATALOG", None)
        os.environ["CAREER_LAB_SCENARIO_V2"] = str(ROOT / row["root"])
        os.environ["CAREER_LAB_SCENARIO_ARCHIVE"] = str(directory / f"archive-{index}")
        app = create_runtime_app(f"sqlite:///{directory}/feedback-{index}.db", provider="local")
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/sessions",
                    json={
                        "schema_version": 2,
                        "scenario": manifest["id"] + "_v2",
                        "work_language": row["work_language"],
                    },
                )
                assert response.status_code == 200, response.text
                created = response.json()
                session = PublishedSession(
                    app,
                    client,
                    created["session_id"],
                    {"Authorization": "Bearer " + created["token"]},
                    row["work_language"],
                )
                subject, feedback = submit(session)
                assert len(feedback["items"]) == 14
                before = session.get("feedback/" + subject).json()
                app.state.handlers.clear()
                assert session.get("feedback/" + subject).json() == before
        finally:
            app.state.store.close()
            app.state.v2_store.db.engine.dispose()


def test_formatted_rule_modules_generate_legacy_feedback(tmp_path: Path) -> None:
    formatted = tmp_path / "formatted" / "v4"
    formatted.mkdir(parents=True)
    for source in (ROOT / "src/career_lab/rubrics/v4").glob("*.py"):
        (formatted / source.name).write_bytes(source.read_bytes())
    for name in RULE_MODULES:
        original = (ROOT / "src/career_lab/rubrics/v4" / name).read_text()
        result = subprocess.run(
            [str(ROOT / ".venv/bin/ruff"), "format", "--isolated", "--line-length", "100", "-"],
            input=original,
            capture_output=True,
            text=True,
            check=True,
        )
        assert ast.dump(ast.parse(result.stdout)) == ast.dump(ast.parse(original))
        (formatted / name).write_text(result.stdout)
    script = """
import sys
from pathlib import Path
import importlib
import career_lab.rubrics
career_lab.rubrics.__path__.insert(0, str(Path(sys.argv[1]).parent))
from tests.regression.test_rule_identity import exercise_feedback, LEGACY_CATALOG, RULE_MODULES
for name in RULE_MODULES:
    module = importlib.import_module("career_lab.rubrics.v4." + name[:-3])
    assert Path(module.__file__).resolve() == (Path(sys.argv[1]) / name).resolve()
from tests.regression.test_protocol_migration import CASES, complete_feedback_digest
from career_lab.rubrics.v4.feedback import FeedbackEngine
exercise_feedback(LEGACY_CATALOG, Path(sys.argv[2]))
from scripts.regression.published import CATALOG
current = Path(sys.argv[2]) / "current"
current.mkdir()
exercise_feedback(CATALOG, current)
for index, case in enumerate(CASES):
    assert complete_feedback_digest(index, FeedbackEngine()) == case['expected_digest']
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(formatted), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_formal_rebind_exports_semantic_rules_without_changing_content(tmp_path: Path) -> None:
    from career_lab.contracts.v2 import EvaluationBundle
    from career_lab.scenarios.v2.loader import load_package
    from career_lab.scenarios.v2.release import content_files, describe, sha

    source = ROOT / json.loads(LEGACY_CATALOG.read_text())["scenarios"][0]["root"]
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
        "scenario-release-v1",
        "--scenario-revision",
        "semantic-rules",
        "--runtime-revision",
        "semantic-rules",
        "--contract-revision",
        "expansion-v3-" + sha((ROOT / "docs/contracts/expansion-v3/manifest.json").read_bytes()),
        "--smoke-database",
        str(tmp_path / "smoke.db"),
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    evaluation = EvaluationBundle.model_validate_json(
        (destination / "runtime/evaluation.json").read_bytes()
    )
    rules = json.loads((destination / evaluation.rules.path).read_bytes())
    assert "files" not in rules
    assert rules["evaluation_version"] == "feedback-rubric-v2-c2.1"
    assert (
        rules["engine_baseline_sha256"]
        == "7b9d79e92355e98f1160f35219ac104bdc90bd05a32edfeb484adf68da21f891"
    )
    before, after = load_package(source), load_package(destination)
    assert content_files(before) == content_files(after)
    assert describe(before, "old").review == describe(after, "new").review
    for ref in before.bundle.files:
        if not ref.path.startswith("runtime/"):
            assert (source / ref.path).read_bytes() == (destination / ref.path).read_bytes()


@pytest.mark.parametrize("legacy", [True, False])
@pytest.mark.parametrize("rebind_hash", [True, False])
def test_tampered_rule_descriptions_are_rejected(
    tmp_path: Path, legacy: bool, rebind_hash: bool
) -> None:
    import hashlib

    from career_lab.contracts import v2 as C
    from career_lab.rubrics.v4.rubric_v2 import install_candidate, load_installed_policies

    refs = install_candidate(tmp_path)
    rules_path = tmp_path / refs["rules"].path
    if legacy:
        source = ROOT / json.loads(LEGACY_CATALOG.read_text())["scenarios"][0]["root"]
        rules_path.write_bytes((source / "evaluation/rules-v4-rubric-v2-c2.json").read_bytes())
    before = rules_path.read_bytes()
    tampered = json.loads(before)
    if legacy:
        tampered["files"]["feedback.py"] = "0" * 64
    else:
        tampered["engine_baseline_sha256"] = "0" * 64
    rules_path.write_text(json.dumps(tampered))
    raw = rules_path.read_bytes() if rebind_hash else before
    rules_ref = C.FileRef(path=rules_path.name, sha256=hashlib.sha256(raw).hexdigest())
    bundle = C.EvaluationBundle(
        id="tampered",
        revision="test",
        rubric=refs["rubric"],
        rules=rules_ref,
        graders=(),
        protocol=rules_ref,
    )
    body = bundle.model_dump_json().encode()
    (tmp_path / "evaluation.json").write_bytes(body)
    with pytest.raises(C.ProtocolError):
        load_installed_policies(
            tmp_path, C.FileRef(path="evaluation.json", sha256=hashlib.sha256(body).hexdigest())
        )
