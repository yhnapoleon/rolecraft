"""Portable registry inputs reject credentials before persisting any member bytes."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from career_lab.contracts.v2.core import FileRef
from career_lab.contracts.v2.research import RuntimeBundle
from career_lab.registry.v3.store import BundleRegistry

SECRET = "synthetic-registry-secret-value"
FORMATS = {
    "json": "application/json",
    "yaml": "application/yaml",
    "toml": "application/toml",
    "txt": "text/plain",
}


def member(root: Path, name: str, raw: bytes, media_type: str = "application/json") -> FileRef:
    (root / name).write_bytes(raw)
    return FileRef(path=name, sha256=hashlib.sha256(raw).hexdigest(), media_type=media_type)


def register_config(
    tmp_path: Path, suffix: str, content: str, media_type: str
) -> tuple[subprocess.CompletedProcess[str], Path, FileRef]:
    source = tmp_path / "source"
    source.mkdir()
    safe = member(source, "safe.json", b'{"mode":"fixture"}')
    config = member(source, "model." + suffix, content.encode(), media_type)
    runtime = RuntimeBundle(
        id="portable-runtime",
        revision="example",
        model=config,
        prompts=(safe,),
        acquisition=safe,
        retrieval=safe,
        decision=safe,
        tools=safe,
        source={"base_commit": "2" * 40, "source_digest": "3" * 64},
    )
    root = member(source, "runtime.json", runtime.model_dump_json().encode())
    registry = tmp_path / "registry"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "career_lab.registry.v3",
            "--registry",
            str(registry),
            "register",
            "--kind",
            "runtime",
            "--source",
            str(source),
            "--manifest",
            root.path,
            "--sha256",
            root.sha256,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result, registry, config


@pytest.mark.parametrize("suffix", FORMATS)
@pytest.mark.parametrize("kind", ["token", "refresh_token", "url_userinfo"])
def test_T1_registry_cli_rejects_credentials_without_persisting_bytes(
    tmp_path: Path, suffix: str, kind: str
) -> None:
    key = "endpoint" if kind == "url_userinfo" else kind
    value = f"https://review-user:{SECRET}@example.invalid/v1" if kind == "url_userinfo" else SECRET
    if suffix == "json":
        content = json.dumps({"settings": {key: value}})
    elif suffix == "yaml":
        content = f'settings:\n  {key}: "{value}"\n'
    else:
        content = f'{key} = "{value}"\n'
    result, registry, _ = register_config(tmp_path, suffix, content, FORMATS[suffix])
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"] == "registry_credentials_forbidden"
    assert SECRET not in result.stdout + result.stderr
    assert all(
        SECRET.encode() not in file.read_bytes() for file in registry.rglob("*") if file.is_file()
    )


@pytest.mark.parametrize(
    "suffix,media,content",
    [
        (
            "json",
            "application/json",
            '{"path":"models/relative.json","endpoint":"https://example.invalid/v1"}',
        ),
        (
            "yaml",
            "application/yaml",
            "path: models/relative.json\nendpoint: https://example.invalid/v1\n",
        ),
        (
            "toml",
            "application/toml",
            'path = "models/relative.json"\nendpoint = "https://example.invalid/v1"\n',
        ),
        (
            "md",
            "text/markdown",
            "# Method\nRead models/relative.json and https://example.invalid/docs.\n",
        ),
    ],
)
def test_T1_relative_references_and_credential_free_documents_remain_portable(
    tmp_path: Path, suffix: str, media: str, content: str
) -> None:
    result, path, config = register_config(tmp_path, suffix, content, media)
    assert result.returncode == 0, result.stdout + result.stderr
    identity = json.loads(result.stdout)["identity"]
    assert BundleRegistry(path).resolve_file(identity, config) == content.encode()


@pytest.mark.parametrize("with_credentials", [False, True])
def test_T1_ipv6_url_authority_uses_the_same_credential_boundary(
    tmp_path: Path, with_credentials: bool
) -> None:
    authority = f"user:{SECRET}@" if with_credentials else ""
    content = json.dumps({"endpoint": f"http://{authority}[::1]:8080/api"})
    result, registry, _ = register_config(tmp_path, "json", content, "application/json")
    if with_credentials:
        assert result.returncode != 0
        assert json.loads(result.stdout)["error"] == "registry_credentials_forbidden"
        assert all(
            SECRET.encode() not in file.read_bytes()
            for file in registry.rglob("*")
            if file.is_file()
        )
    else:
        assert result.returncode == 0, result.stdout + result.stderr
