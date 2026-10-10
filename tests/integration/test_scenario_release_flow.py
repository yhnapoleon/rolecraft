"""Candidate author CLI uses current loaders and isolated standard session creation."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_scenario_role_contract import declaration

from career_lab.api.vertical_runtime import create_runtime_app
from career_lab.contracts.v2.research import EvaluationBundle

ROOT = Path(__file__).resolve().parents[2]


def source_package(language: str) -> Path:
    index = json.loads((ROOT / "scenarios/pm_pilot/v2/installed/current.json").read_text())
    return ROOT / index["main"][language]["root"]


def run_compiler(*arguments: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "career_lab.scenario_compiler", *map(str, arguments)],
        capture_output=True,
        text=True,
        check=False,
    )


def build_arguments(tmp_path: Path, source: Path) -> list[str | Path]:
    declared = tmp_path / "declaration.json"
    declared.write_text(json.dumps(declaration()))
    raw = (source / "runtime/evaluation.json").read_bytes()
    evaluation = EvaluationBundle.model_validate_json(raw)
    return [
        "build",
        "--source",
        source,
        "--output",
        tmp_path / "candidate",
        "--declaration",
        declared,
        "--author-id",
        "example-author",
        "--revision",
        "candidate-example",
        "--evaluation-id",
        evaluation.id,
        "--evaluation-revision",
        evaluation.revision,
        "--evaluation-sha256",
        hashlib.sha256(raw).hexdigest(),
    ]


@pytest.mark.parametrize("language", ["zh", "en"])
def test_BUILD_01_built_current_package_starts_through_standard_session_api(
    tmp_path: Path, language: str
) -> None:
    source = source_package(language)
    before = {
        str(path.relative_to(source)): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    result = run_compiler(*build_arguments(tmp_path, source))
    assert result.stdout.strip(), result.stderr
    report = json.loads(result.stdout)
    assert report["package_status"] == "valid"
    assert report["status"] == "needs_confirmation"
    assert report["published"] is False
    candidate = tmp_path / "candidate"
    checked = run_compiler("validate", "--candidate", candidate)
    assert json.loads(checked.stdout)["package_status"] == "valid"
    app = create_runtime_app(
        "sqlite:///" + str(tmp_path / "isolated.db"), scenario_root=candidate / "package"
    )
    try:
        with TestClient(app) as client:
            created = client.post(
                "/sessions",
                json={"schema_version": 2, "scenario": "pm_pilot_v2", "work_language": language},
            )
            assert created.status_code == 200, created.text
            body = created.json()
            state = client.get(
                "/sessions/" + body["session_id"],
                headers={"Authorization": "Bearer " + body["token"]},
            )
            assert state.status_code == 200, state.text
    finally:
        app.state.store.close()
    assert before == {
        str(path.relative_to(source)): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize(
    "defect,code,location",
    [
        ("fact", "fact_source_value_mismatch", "facts.json"),
        ("probe", "hidden_probe_in_public_material", "probes.json"),
    ],
)
def test_BUILD_03_conflicts_and_probe_leaks_reject_candidate_with_source_location(
    tmp_path: Path, defect: str, code: str, location: str
) -> None:
    import shutil

    source = tmp_path / "source"
    shutil.copytree(source_package("zh"), source)
    manifest = json.loads((source / "manifest.json").read_text())
    if defect == "fact":
        changed = "facts.json"
        facts = json.loads((source / changed).read_text())
        facts[0]["value"] = "unsupported-source-value"
        raw = json.dumps(facts, ensure_ascii=False).encode()
    else:
        changed = next(name for name in manifest["public_files"] if name.endswith(".md"))
        probes = json.loads((source / "probes.json").read_text())
        query = next(probe["query"] for probe in probes if not probe["public"])
        raw = (source / changed).read_bytes() + ("\n" + query + "\n").encode()
    (source / changed).write_bytes(raw)
    for ref in manifest["files"]:
        if ref["path"] == changed:
            ref["sha256"] = hashlib.sha256(raw).hexdigest()
    (source / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
    result = run_compiler(*build_arguments(tmp_path, source))
    report = json.loads(result.stdout)
    assert report["status"] == "failed"
    assert report["published"] is False
    assert report["error_code"] == code
    assert report["issues"] == [{"code": code, "location": location}]
    assert not (tmp_path / "candidate" / "package").exists()


def test_BUILD_05_dangling_output_link_cannot_redirect_candidate_writes(tmp_path: Path) -> None:
    arguments = build_arguments(tmp_path, source_package("zh"))
    output = tmp_path / "candidate"
    redirected = tmp_path / "unexpected-output"
    output.symlink_to(redirected, target_is_directory=True)
    result = run_compiler(*arguments)
    report = json.loads(result.stdout)
    assert report["error_code"] == "candidate_destination_not_fresh"
    assert output.is_symlink()
    assert not redirected.exists()


def test_BUILD_06_failed_and_unreadable_attempts_remain_in_the_generation_denominator(
    tmp_path: Path,
) -> None:
    attempts = tmp_path / "attempts"
    attempts.mkdir()
    prepared = build_arguments(tmp_path, source_package("zh"))
    good = list(prepared)
    good[good.index("--output") + 1] = attempts / "valid"
    assert json.loads(run_compiler(*good).stdout)["package_status"] == "valid"
    bad = list(prepared)
    bad[bad.index("--output") + 1] = attempts / "invalid"
    bad[bad.index("--source") + 1] = tmp_path / "missing-source"
    assert json.loads(run_compiler(*bad).stdout)["status"] == "failed"
    unreadable = attempts / "unreadable"
    unreadable.mkdir()
    (unreadable / "checkpoint.json").write_text("{incomplete")
    result = run_compiler("attempts", "--root", attempts)
    assert result.stdout.strip(), result.stderr
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["total_attempts"] == 3
    assert report["by_status"] == {"candidate": 1, "failed": 1, "unresolved": 1}
    assert report["by_generator"] == {"manual": 2, "unknown": 1}
    assert len(report["attempts"]) == 3
    assert report["published"] is False


@pytest.mark.parametrize("field", ["id", "revision", "sha256"])
def test_BUILD_01_evaluation_identity_must_match_all_supplied_fields(
    tmp_path: Path, field: str
) -> None:
    arguments = build_arguments(tmp_path, source_package("zh"))
    option = "--evaluation-" + field
    arguments[arguments.index(option) + 1] = "0" * 64 if field == "sha256" else "another-identity"
    report = json.loads(run_compiler(*arguments).stdout)
    assert report["status"] == "failed"
    assert report["error_code"] == "candidate_evaluation_mismatch"
    assert not (tmp_path / "candidate" / "package").exists()


def test_BUILD_01_new_evaluation_identity_is_not_a_hardcoded_candidate(
    tmp_path: Path,
) -> None:
    import shutil

    source = tmp_path / "source"
    shutil.copytree(source_package("en"), source)
    member = source / "runtime/evaluation.json"
    evaluation = EvaluationBundle.model_validate_json(member.read_bytes()).model_copy(
        update={"id": "approved-evaluation", "revision": "next-revision"}
    )
    raw = evaluation.model_dump_json().encode()
    member.write_bytes(raw)
    manifest = json.loads((source / "manifest.json").read_text())
    for ref in manifest["files"]:
        if ref["path"] == "runtime/evaluation.json":
            ref["sha256"] = hashlib.sha256(raw).hexdigest()
    (source / "manifest.json").write_text(json.dumps(manifest))
    report = json.loads(run_compiler(*build_arguments(tmp_path, source)).stdout)
    assert report["package_status"] == "valid", report
    assert report["evaluation"] == {
        "id": evaluation.id,
        "revision": evaluation.revision,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_BUILD_02_author_owned_review_file_does_not_grant_publication(tmp_path: Path) -> None:
    built = json.loads(run_compiler(*build_arguments(tmp_path, source_package("zh"))).stdout)
    candidate = tmp_path / "candidate"
    (candidate / "review.json").write_text(
        json.dumps(
            {
                "author": "example-author",
                "reviewer": "example-author",
                "verdict": "accepted",
                "scenario_sha256": built["scenario_sha256"],
            }
        )
    )
    result = run_compiler("publish", "--candidate", candidate)
    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert report["published"] is False
    assert report["status"] == "needs_authorization"
    assert report["error_code"] == "scenario_release_authority_unavailable"


def test_BUILD_05_existing_candidate_cannot_be_overwritten(tmp_path: Path) -> None:
    arguments = build_arguments(tmp_path, source_package("zh"))
    assert json.loads(run_compiler(*arguments).stdout)["package_status"] == "valid"
    candidate = tmp_path / "candidate"
    before = {
        str(path.relative_to(candidate)): path.read_bytes()
        for path in candidate.rglob("*")
        if path.is_file()
    }
    refused = json.loads(run_compiler(*arguments).stdout)
    assert refused["error_code"] == "candidate_destination_not_fresh"
    assert before == {
        str(path.relative_to(candidate)): path.read_bytes()
        for path in candidate.rglob("*")
        if path.is_file()
    }
