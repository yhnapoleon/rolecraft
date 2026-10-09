"""Operators register and recover fixed file identities through the module CLI."""

import json
import subprocess
import sys
from pathlib import Path

from pydantic import JsonValue
from test_bundle_registry_flow import evaluation, runtime


def invoke(registry: Path, *arguments: str) -> tuple[int, dict[str, JsonValue]]:
    result = subprocess.run(
        [sys.executable, "-m", "career_lab.registry.v3", "--registry", str(registry), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.strip(), result.stderr
    return result.returncode, json.loads(result.stdout)


def test_REG_01_cli_preserves_original_registration_after_conflict(tmp_path: Path) -> None:
    source = tmp_path / "source"
    registry = tmp_path / "registry"
    ref = runtime(source)
    code, registered = invoke(
        registry,
        "register",
        "--kind",
        "runtime",
        "--source",
        str(source),
        "--manifest",
        ref.path,
        "--sha256",
        ref.sha256,
    )
    assert code == 0
    identity = registered["identity"]
    assert registered["execution_verified"] is False
    changed = runtime(source, prompt="Changed prompt")
    code, failed = invoke(
        registry,
        "register",
        "--kind",
        "runtime",
        "--source",
        str(source),
        "--manifest",
        changed.path,
        "--sha256",
        changed.sha256,
    )
    assert code == 2
    assert failed["error"] == "registry_version_immutable"
    code, loaded = invoke(registry, "load", identity)
    assert code == 0
    assert (
        loaded["manifest"]["prompts"][0]["sha256"]
        != json.loads((source / "runtime.json").read_text())["prompts"][0]["sha256"]
    )


def test_REG_04_cli_binds_versions_and_rejects_evaluation_changes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    registry = tmp_path / "registry"
    ids = []
    for kind, ref in (("runtime", runtime(source)), ("evaluation", evaluation(source))):
        code, record = invoke(
            registry,
            "register",
            "--kind",
            kind,
            "--source",
            str(source),
            "--manifest",
            ref.path,
            "--sha256",
            ref.sha256,
        )
        assert code == 0
        ids.append(record["identity"])
    code, bound = invoke(registry, "bind", "--runtime", ids[0], "--evaluation", ids[1])
    assert code == 0
    assert bound["binding"] == {"runtime_id": ids[0], "evaluation_id": ids[1]}
    other = evaluation(source, revision="2")
    code, record = invoke(
        registry,
        "register",
        "--kind",
        "evaluation",
        "--source",
        str(source),
        "--manifest",
        other.path,
        "--sha256",
        other.sha256,
    )
    assert code == 0
    code, failed = invoke(
        registry,
        "compare",
        "--runtime",
        ids[0],
        "--evaluation",
        ids[1],
        "--candidate-runtime",
        ids[0],
        "--candidate-evaluation",
        record["identity"],
    )
    assert code == 2
    assert failed["error"] == "registry_evaluation_changed"


def test_REG_02_cli_reports_changed_dependencies(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ref = runtime(source)
    (source / "prompt.json").write_text('{"text":"unregistered revision"}')
    code, result = invoke(
        tmp_path / "registry",
        "register",
        "--kind",
        "runtime",
        "--source",
        str(source),
        "--manifest",
        ref.path,
        "--sha256",
        ref.sha256,
    )
    assert code == 2
    assert result == {"error": "file_hash_mismatch", "execution_verified": False}


def test_REG_03_cli_rejects_nonportable_files_without_echoing_content(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ref = runtime(source, prompt="/Users/private-author/model")
    code, result = invoke(
        tmp_path / "registry",
        "register",
        "--kind",
        "runtime",
        "--source",
        str(source),
        "--manifest",
        ref.path,
        "--sha256",
        ref.sha256,
    )
    assert code == 2
    assert result == {"error": "registry_machine_path_forbidden", "execution_verified": False}
