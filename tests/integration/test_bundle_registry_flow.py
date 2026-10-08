"""File-only registry core; shared CLI and runner installation are pending."""

import hashlib
from pathlib import Path

import pytest
from pydantic import BaseModel, JsonValue

from career_lab.contracts.v2.core import FileRef, ProtocolError, canonical
from career_lab.contracts.v2.research import (
    CandidateBundle,
    EvaluationBundle,
    RuntimeBundle,
    SkillBundle,
)
from career_lab.registry.v3.store import BundleRegistry


def write_json(root: Path, path: str, value: BaseModel | JsonValue) -> FileRef:
    raw = canonical(
        value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    ).encode()
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return FileRef(path=path, sha256=hashlib.sha256(raw).hexdigest())


def runtime(
    root: Path, *, revision: str = "1", prompt: str = "Read authorized evidence"
) -> FileRef:
    config = write_json(root, "config.json", {"mode": "fixture"})
    manifest = RuntimeBundle(
        id="reference-runtime",
        revision=revision,
        model=config,
        prompts=(write_json(root, "prompt.json", {"text": prompt}),),
        acquisition=config,
        retrieval=config,
        decision=config,
        tools=config,
        source={"base_commit": "2" * 40, "source_digest": "3" * 64},
    )
    return write_json(root, "runtime.json", manifest)


def test_REG_01_same_version_cannot_overwrite_an_existing_runtime(tmp_path: Path) -> None:
    source = tmp_path / "source"
    registry = BundleRegistry(tmp_path / "registry")
    first = runtime(source)
    original_raw = (source / first.path).read_bytes()
    record_id = registry.register("runtime", source, first)
    assert registry.register("runtime", source, first) == record_id
    changed = runtime(source, prompt="Changed prompt")
    with pytest.raises(ProtocolError) as rejected:
        registry.register("runtime", source, changed)
    assert rejected.value.code == "registry_version_immutable"
    assert rejected.value.status == 409
    assert (
        registry.load(record_id).prompts[0].sha256
        != RuntimeBundle.model_validate_json((source / "runtime.json").read_bytes())
        .prompts[0]
        .sha256
    )
    assert registry.resolve_file(record_id, first) == original_raw


def evaluation(root: Path, *, revision: str = "1") -> FileRef:
    rules = write_json(root, "rules.json", {"mode": "advisory"})
    bundle = EvaluationBundle(
        id="evaluation", revision=revision, rubric=rules, rules=rules, graders=(), protocol=rules
    )
    return write_json(root, "evaluation.json", bundle)


def candidate(root: Path) -> FileRef:
    runtime_ref = runtime(root)
    bundle = CandidateBundle(
        id="candidate-one",
        parent=runtime_ref,
        runtime=runtime_ref,
        evaluation=evaluation(root),
        changes={},
        hypothesis="Registry mechanism fixture, no quality claim",
        allowed_data=(),
        source_splits=("dev",),
        budget={"actions": 1, "model_calls": 0, "wall_seconds": 10},
    )
    return write_json(root, "candidate.json", bundle)


def test_REG_02_candidate_captures_transitive_runtime_members(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ref = candidate(source)
    prompt_ref = RuntimeBundle.model_validate_json((source / "runtime.json").read_bytes()).prompts[
        0
    ]
    original = (source / "prompt.json").read_bytes()
    registry = BundleRegistry(tmp_path / "registry")
    record_id = registry.register("candidate", source, ref)
    assert registry.resolve_file(record_id, prompt_ref) == original


@pytest.mark.parametrize("invalid_member", ["missing", "changed"])
def test_REG_02_unavailable_or_drifted_dependency_rejects_candidate(
    tmp_path: Path, invalid_member: str
) -> None:
    source = tmp_path / "source"
    ref = candidate(source)
    prompt = source / "prompt.json"
    if invalid_member == "missing":
        prompt.unlink()
    else:
        prompt.write_text('{"text":"changed after manifest freeze"}')
    registry = BundleRegistry(tmp_path / "registry")
    with pytest.raises(ProtocolError) as failure:
        registry.register("candidate", source, ref)
    assert failure.value.code == (
        "file_missing" if invalid_member == "missing" else "file_hash_mismatch"
    )


def test_REG_03_credentials_in_referenced_config_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ref = runtime(source, prompt="ordinary prompt")
    model = RuntimeBundle.model_validate_json((source / ref.path).read_bytes())
    secret = write_json(source, "model-config.json", {"api_key": "synthetic-test-value"})
    ref = write_json(source, "runtime.json", model.model_copy(update={"model": secret}))
    with pytest.raises(ProtocolError) as rejected:
        BundleRegistry(tmp_path / "registry").register("runtime", source, ref)
    assert rejected.value.code == "registry_credentials_forbidden"


@pytest.mark.parametrize(
    "path", ["/Users/author/model", "C:\\models\\local", "\\\\host\\share\\model"]
)
def test_REG_03_machine_paths_are_not_portable(tmp_path: Path, path: str) -> None:
    source = tmp_path / "source"
    ref = runtime(source, prompt=path)
    with pytest.raises(ProtocolError) as rejected:
        BundleRegistry(tmp_path / "registry").register("runtime", source, ref)
    assert rejected.value.code == "registry_machine_path_forbidden"


def test_REG_03_yaml_config_cannot_bypass_credential_check(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ref = runtime(source)
    model = RuntimeBundle.model_validate_json((source / ref.path).read_bytes())
    raw = b"api_key: synthetic-test-value\n"
    (source / "config.yaml").write_bytes(raw)
    config = FileRef(
        path="config.yaml", sha256=hashlib.sha256(raw).hexdigest(), media_type="application/yaml"
    )
    ref = write_json(source, "runtime.json", model.model_copy(update={"model": config}))
    with pytest.raises(ProtocolError) as rejected:
        BundleRegistry(tmp_path / "registry").register("runtime", source, ref)
    assert rejected.value.code == "registry_credentials_forbidden"


def test_REG_04_comparison_rejects_changed_evaluation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    registry = BundleRegistry(tmp_path / "registry")
    runtime_id = registry.register("runtime", source, runtime(source))
    evaluation_id = registry.register("evaluation", source, evaluation(source))
    baseline = registry.bind(runtime_id, evaluation_id)
    other_id = registry.register("evaluation", source, evaluation(source, revision="2"))
    candidate_binding = registry.bind(runtime_id, other_id)
    with pytest.raises(ProtocolError) as rejected:
        registry.compare(baseline, candidate_binding)
    assert rejected.value.code == "registry_evaluation_changed"


def test_REG_05_new_runtime_does_not_change_an_existing_binding(tmp_path: Path) -> None:
    source = tmp_path / "source"
    registry = BundleRegistry(tmp_path / "registry")
    first = registry.register("runtime", source, runtime(source))
    evaluation_id = registry.register("evaluation", source, evaluation(source))
    pinned = registry.bind(first, evaluation_id)
    original_model = registry.load(pinned.runtime_id)
    second = registry.register(
        "runtime", source, runtime(source, revision="2", prompt="New prompt")
    )
    new_binding = registry.bind(second, evaluation_id)
    assert registry.load(pinned.runtime_id) == original_model
    assert registry.load(new_binding.runtime_id).revision == "2"
    assert new_binding.runtime_id != pinned.runtime_id
    registry.compare(pinned, new_binding)


def test_REG_02_model_registration_is_not_owned_by_this_registry(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ref = runtime(source)
    with pytest.raises(ProtocolError) as rejected:
        BundleRegistry(tmp_path / "registry").register("model", source, ref)
    assert rejected.value.code == "registry_schema_unsupported"


def test_REG_02_scoring_is_not_promoted_by_unverified_registration(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ref = evaluation(source)
    model = EvaluationBundle.model_validate_json((source / ref.path).read_bytes())
    unverified = write_json(source, "adoption.json", {"claim": "unverified fixture"})
    ref = write_json(
        source,
        "evaluation.json",
        model.model_copy(
            update={
                "mode": "scoring",
                "calibration": unverified,
                "adoption_record": unverified,
            }
        ),
    )
    with pytest.raises(ProtocolError) as rejected:
        BundleRegistry(tmp_path / "registry").register("evaluation", source, ref)
    assert rejected.value.code == "scoring_adoption_not_authorized"


def test_REG_02_missing_skill_member_cannot_hide_behind_bundle(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ref = runtime(source)
    model = RuntimeBundle.model_validate_json((source / ref.path).read_bytes())
    missing = FileRef(path="missing-skill.json", sha256="1" * 64)
    skills = write_json(
        source, "skills.json", SkillBundle(id="skills", revision="1", members=(missing,))
    )
    ref = write_json(source, "runtime.json", model.model_copy(update={"skills": skills}))
    with pytest.raises(ProtocolError) as rejected:
        BundleRegistry(tmp_path / "registry").register("runtime", source, ref)
    assert rejected.value.code == "file_missing"


def test_REG_02_unreadable_store_is_an_explicit_protocol_failure(tmp_path: Path) -> None:
    source = tmp_path / "source"
    root = tmp_path / "registry"
    registry = BundleRegistry(root)
    identity = registry.register("runtime", source, runtime(source))
    (root / "registry.sqlite").write_bytes(b"injected storage failure")
    with pytest.raises(ProtocolError) as rejected:
        registry.load(identity)
    assert rejected.value.code == "registry_storage_unavailable"


@pytest.mark.parametrize("media_type", ["text/plain", "application/octet-stream"])
def test_REG_03_mislabelled_configuration_does_not_bypass_secret_checks(
    tmp_path: Path, media_type: str
) -> None:
    source = tmp_path / "source"
    ref = runtime(source)
    model = RuntimeBundle.model_validate_json((source / ref.path).read_bytes())
    raw = b"api_key: synthetic-test-value\nmodel_path: /Users/author/model\n"
    (source / "config.yaml").write_bytes(raw)
    config = FileRef(
        path="config.yaml", sha256=hashlib.sha256(raw).hexdigest(), media_type=media_type
    )
    ref = write_json(source, "runtime.json", model.model_copy(update={"model": config}))
    with pytest.raises(ProtocolError) as rejected:
        BundleRegistry(tmp_path / "registry").register("runtime", source, ref)
    assert rejected.value.code in {
        "registry_credentials_forbidden",
        "registry_member_format_unsupported",
    }


def test_REG_03_relative_path_with_tmp_segment_remains_portable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ref = runtime(source)
    model = RuntimeBundle.model_validate_json((source / ref.path).read_bytes())
    config = write_json(source, "fixtures/tmp/config.json", {"mode": "fixture"})
    ref = write_json(source, "runtime.json", model.model_copy(update={"model": config}))
    registry = BundleRegistry(tmp_path / "registry")
    registered = registry.register("runtime", source, ref)
    assert registry.resolve_file(registered, config) == b'{"mode":"fixture"}'


def test_REG_03_markdown_prompt_is_not_required_to_be_yaml(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ref = runtime(source)
    model = RuntimeBundle.model_validate_json((source / ref.path).read_bytes())
    raw = (
        b"# Skill\n\n**Goal:** Read authorized evidence.\n\n"
        b"- Cite sources.\n- Preserve uncertainty.\n"
    )
    (source / "prompt.md").write_bytes(raw)
    prompt = FileRef(
        path="prompt.md", sha256=hashlib.sha256(raw).hexdigest(), media_type="text/markdown"
    )
    ref = write_json(source, "runtime.json", model.model_copy(update={"prompts": (prompt,)}))
    registry = BundleRegistry(tmp_path / "registry")
    registered = registry.register("runtime", source, ref)
    assert registry.resolve_file(registered, prompt) == raw


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"secret: synthetic-test-value\n", "registry_credentials_forbidden"),
        (b"model_path: C:\\models\\local\n", "registry_machine_path_forbidden"),
    ],
)
@pytest.mark.parametrize("filename", ["config.yaml", "config.txt"])
def test_REG_03_plain_text_cannot_hide_secret_or_windows_path(
    tmp_path: Path, raw: bytes, code: str, filename: str
) -> None:
    source = tmp_path / "source"
    ref = runtime(source)
    model = RuntimeBundle.model_validate_json((source / ref.path).read_bytes())
    (source / filename).write_bytes(raw)
    config = FileRef(path=filename, sha256=hashlib.sha256(raw).hexdigest(), media_type="text/plain")
    ref = write_json(source, "runtime.json", model.model_copy(update={"model": config}))
    with pytest.raises(ProtocolError) as rejected:
        BundleRegistry(tmp_path / "registry").register("runtime", source, ref)
    assert rejected.value.code == code
